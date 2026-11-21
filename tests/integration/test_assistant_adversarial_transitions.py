"""Adversarial HTTP state journeys. Synthetic receipts are never live Excel proof."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import unittest

from tests.integration import test_assistant_v2_journey as journey
from tests.support.assistant_flow import AssistantBranchPlanner


class AssistantAdversarialTransitionsTests(unittest.TestCase):
    setUp = journey.AssistantV2JourneyTests.setUp
    tearDown = journey.AssistantV2JourneyTests.tearDown
    request = journey.AssistantV2JourneyTests.request
    auth = journey.AssistantV2JourneyTests.auth
    post = journey.AssistantV2JourneyTests.post
    draft = journey.AssistantV2JourneyTests.draft
    compute = journey.AssistantV2JourneyTests.compute
    freeze = journey.AssistantV2JourneyTests.freeze
    approval_body = journey.AssistantV2JourneyTests.approval_body
    apply_body = journey.AssistantV2JourneyTests.apply_body

    def assert_source_intact(self):
        self.assertEqual(Path(self.temp.name, 'Transactions.csv').read_text(encoding='utf-8'),
                         'ID,Amount\nA,10\nB,-3\nC,5\n')

    def test_two_simultaneous_handoffs_have_exactly_one_winner_and_replay_stays_consumed(self):
        self.freeze()
        self.post('approvals', self.approval_body())
        body, headers, barrier = self.apply_body(), self.auth(), Barrier(3)

        def attempt():
            barrier.wait(timeout=5)
            return self.request('POST', '/api/assistant/apply', body, headers)

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(attempt) for _ in range(2)]
            barrier.wait(timeout=5)
            responses = [future.result(timeout=15) for future in futures]
        winners = [payload for status, _, payload in responses if status == 200]
        self.assertEqual(len(winners), 1, responses)
        self.assertEqual(winners[0]['stage'], 'handoff')
        self.assertEqual(winners[0]['result']['rows'], [['12']])
        self.assertTrue(winners[0]['apply']['approval']['consumed'])
        for status, _, payload in responses:
            if status != 200:
                self.assertIn(status, (409, 429, 500), payload)
                self.assertIn(payload['error']['code'], ('AF_WRITE_PARTIAL', 'EXCEL_BUSY'))
        status, _, replay = self.request('POST', '/api/assistant/apply', body, headers)
        self.assertNotEqual(status, 200)
        self.assertEqual(replay['error']['code'], 'AF_WRITE_PARTIAL')
        self.assertTrue(replay['error']['approvalConsumed'])
        self.assertIsNone(replay['error']['written'])
        self.assert_source_intact()

    def test_every_receipt_identity_dimension_and_marker_is_bound_after_consumption(self):
        changes = {'handoffId':'different', 'specFingerprint':'sha256:'+'0'*64,
                   'previewHash':'sha256:'+'1'*64, 'resultDigest':'sha256:'+'2'*64,
                   'sheet':'OtherSheet', 'marker':'OTHER_MARKER', 'rowCount':2, 'columnCount':2}
        for field, changed in changes.items():
            with self.subTest(field=field):
                self.freeze()
                self.post('approvals', self.approval_body())
                handoff = self.post('apply', self.apply_body())
                receipt = {**handoff['receiptBinding'], 'verified':True, field:changed}
                status, _, rejected = self.request('POST', '/api/assistant/apply',
                    {'receipt':receipt, 'appliedAt':'2026-11-01T03:00:00.000Z'}, self.auth())
                self.assertNotEqual(status, 200)
                self.assertEqual(rejected['error']['code'], 'AF_WRITE_PARTIAL')
                self.assertTrue(rejected['error']['approvalConsumed'])
                self.assertIsNone(rejected['error']['written'])
                self.assertFalse(rejected['error']['retryable'])
                self.assertEqual(self.post('state')['stage'], 'partial')
                self.post('record', expected=409)
                self.assert_source_intact()

    def test_same_workbook_name_with_different_document_identity_blocks_before_consume(self):
        self.freeze()
        self.post('approvals', self.approval_body())
        body = self.apply_body()
        body['workbookIdentity'] = {**self.identity, 'documentHash':'sha256:'+'0'*64}
        rejected = self.post('apply', body, expected=409)
        self.assertEqual(rejected['error']['code'], 'AF_SPEC_STALE')
        self.assertIs(rejected['error']['approvalConsumed'], False)
        self.assertNotIn('result', rejected)
        self.assertEqual(self.post('state')['stage'], 'approved')
        # The failed identity never consumed the valid exact-identity approval.
        self.assertEqual(self.post('apply', self.apply_body())['result']['rows'], [['12']])
        self.assert_source_intact()

    def test_branch_b_preview_cannot_be_used_to_freeze_branch_a(self):
        branches = self.compute(file_source=True)
        self.assertNotEqual(branches['branches'][0]['resultDigest'], branches['branches'][1]['resultDigest'])
        identity = {'name':'Synthetic', 'documentHash':'sha256:'+'a'*64}
        rejected = self.post('freeze', {'branchId':'A','createdAt':'2026-11-01T03:00:00.000Z',
            'workbookIdentity':identity,'acknowledgeMissingControl':False,
            'expectedPlanningHash':branches['planningHash'],
            'expectedPreviewHash':branches['branches'][1]['previewHash'],
            'expectedResultDigest':branches['branches'][1]['resultDigest']}, expected=409)
        self.assertEqual(rejected['error']['code'], 'AF_SPEC_STALE')
        state = self.post('state')
        self.assertEqual(state['stage'], 'branched')
        self.assertIsNone(state['spec'])
        self.assert_source_intact()

    def test_missing_control_ack_is_explicit_at_freeze_and_approval_not_a_pass_label(self):
        class NoControlPlanner(AssistantBranchPlanner):
            def propose(self, payload):
                result = super().propose(payload)
                for branch in result['branches']:
                    branch['controlTotal'] = None
                return result

        self.draft(file_source=True)
        self.server.app.assistant_plan_runner = NoControlPlanner()
        planning = self.post('plan-draft', {'prompt':'Sum Amount with no independent control total.',
            'answers':[], 'acknowledged':True})
        self.selection['mode'] = 'compute'
        self.post('ingest', {'requests':[self.selection], 'expectedPlanningHash':planning['planningHash']})
        branches = self.post('branches')
        self.branch = branches['branches'][0]
        self.assertEqual(self.branch['rows'], [['12']])
        self.assertFalse(self.branch['reconciliation']['passed'])
        self.assertTrue(self.branch['selectable'])
        self.identity = {'name':'Synthetic', 'documentHash':'sha256:'+'a'*64}
        freeze_body = {'branchId':'A','createdAt':'2026-11-01T03:00:00.000Z',
            'workbookIdentity':self.identity,'acknowledgeMissingControl':False,
            'expectedPlanningHash':branches['planningHash'], 'expectedPreviewHash':self.branch['previewHash'],
            'expectedResultDigest':self.branch['resultDigest']}
        status, _, blocked = self.request('POST','/api/assistant/freeze',freeze_body,self.auth())
        self.assertNotEqual(status, 200)
        self.assertFalse(self.server.app.assistant.approval_consumed())
        self.frozen = self.post('freeze', {**freeze_body,'acknowledgeMissingControl':True})
        self.assertIn('unverified', self.frozen['spec']['labels'])
        self.assertEqual(self.frozen['spec']['reconcileHash'], self.branch['reconciliation']['reconcileHash'])
        self.assertFalse(self.post('state')['branches'][0]['reconciliation']['passed'])
        body = self.approval_body()
        body['acknowledged'] = False
        status, _, blocked = self.request('POST','/api/assistant/approvals',body,self.auth())
        self.assertNotEqual(status, 200)
        self.assertEqual(self.post('approvals', self.approval_body())['stage'],'approved')
        self.assert_source_intact()


if __name__ == '__main__':
    unittest.main()
