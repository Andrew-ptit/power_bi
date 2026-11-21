"""Transport-scoped evidence captures are reads, never write grants."""
import base64
import hashlib
import unittest
from pbip_assistant.errors import InputError
from tests.support.preparation_images import native_package


def digest(data): return 'sha256:' + hashlib.sha256(data).hexdigest()


class PreservationEvidenceTests(unittest.TestCase):
    def setUp(self):
        from pbip_assistant.sources.preparation.evidence import PreservationEvidenceStore
        self.now = 0
        self.store = PreservationEvidenceStore(clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.image = {'version':1,'sheets':[{'sheetId':'native','name':'Orders','rowOffset':0,'columnOffset':0,
            'values':[['Key']],'formulas':[['Key']],'formulaCells':[],'numberFormats':[['General']]}]}
        self.payload = native_package(self.image)

    def capture(self):
        start=self.store.begin('transport',len(self.payload),digest(self.payload))
        self.store.chunk('transport',start['uploadId'],0,0,digest(self.payload),base64.b64encode(self.payload).decode())
        return self.store.finish('transport',start['uploadId'],self.image)

    def test_complete_capture_is_opaque_bound_to_transport_and_cleanup_reclaims_bytes(self):
        result=self.capture()
        self.assertEqual(set(result),{'evidenceId','preservation','fullFingerprint'})
        resolved=self.store.resolve('transport',result['evidenceId'])
        self.assertEqual(resolved['packageFingerprint'],result['preservation']['packageFingerprint'])
        self.assertIn('parts',resolved['evidence'])
        self.assertGreater(self.store.usage,0)
        with self.assertRaises(InputError):self.store.resolve('other',result['evidenceId'])
        self.store.transport_closed('transport')
        self.assertEqual(self.store.usage,0)
        with self.assertRaises(InputError):self.store.resolve('transport',result['evidenceId'])

    def test_sequential_chunks_accept_identical_retry_reject_conflict_and_release_reservation(self):
        start=self.store.begin('transport',len(self.payload),digest(self.payload))
        args=('transport',start['uploadId'],0,0,digest(self.payload),base64.b64encode(self.payload).decode())
        self.store.chunk(*args);self.store.chunk(*args)
        with self.assertRaises(InputError):self.store.chunk('transport',start['uploadId'],0,0,digest(b'x'),'eA==')
        self.assertEqual(self.store.usage,0)
        with self.assertRaises(InputError):self.store.finish('transport',start['uploadId'],self.image)

    def test_full_package_digest_and_semantic_shape_are_verified(self):
        start=self.store.begin('transport',len(self.payload),digest(b'wrong'))
        self.store.chunk('transport',start['uploadId'],0,0,digest(self.payload),base64.b64encode(self.payload).decode())
        with self.assertRaises(InputError):self.store.finish('transport',start['uploadId'],self.image)
        self.assertEqual(self.store.usage,0)
        self.image['unexpected']=True
        with self.assertRaises(InputError):self.capture()
        self.assertEqual(self.store.usage,0)

    def test_native_package_and_semantic_capture_must_match_before_opaque_receipt(self):
        self.image['sheets'][0]['values'][0][0] = 'race'
        self.image['sheets'][0]['formulas'][0][0] = 'race'
        with self.assertRaises(InputError): self.capture()
        self.assertEqual(self.store.usage, 0)

    def test_completed_capture_fifo_releases_only_volatile_cache(self):
        first = self.capture()
        for _ in range(64): latest = self.capture()
        with self.assertRaises(InputError): self.store.resolve('transport', first['evidenceId'])
        self.assertEqual(self.store.resolve('transport', latest['evidenceId'])['fullFingerprint'], latest['fullFingerprint'])
        self.assertLessEqual(len(self.store._completed), 64)

    def test_reservations_account_process_budget_and_cannot_survive_ttl(self):
        from pbip_assistant.sources.preparation.evidence import PreservationEvidenceStore
        from pbip_assistant.sources.preparation.evidence import PhysicalBudget
        budget=PhysicalBudget(30);budget.replace_usage("journal",15)
        bounded=PreservationEvidenceStore(clock=lambda:self.now,max_bytes=20,budget=budget)
        self.addCleanup(bounded.close)
        bounded.begin('transport',10,digest(b'x'))
        with self.assertRaises(InputError):bounded.begin('transport',10,digest(b'y'))
        self.now=1800;bounded.expire();self.assertEqual(bounded.usage,0)
        bounded.begin('transport',10,digest(b'x'))
        self.now=28800+1800;bounded.expire();self.assertEqual(bounded.usage,0)


class PhysicalBudgetTests(unittest.TestCase):
    def test_rejected_growth_keeps_prior_lease_and_release_frees_other_owner(self):
        from pbip_assistant.sources.preparation.evidence import PhysicalBudget
        budget=PhysicalBudget(30)
        budget.replace_usage('journal',20)
        budget.replace_usage('evidence',10)
        with self.assertRaises(InputError):budget.replace_usage('journal',21)
        self.assertEqual(budget.usage,30)
        budget.replace_usage('evidence',0)
        budget.replace_usage('journal',30)
        self.assertEqual(budget.usage,30)
        budget.replace_usage('journal',0)
        self.assertEqual(budget.usage,0)

    def test_aggregate_concurrent_lease_growth_never_overcommits(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from pbip_assistant.sources.preparation.evidence import PhysicalBudget
        budget=PhysicalBudget(30);gate=Barrier(2)
        def reserve(key):
            gate.wait()
            try:budget.replace_usage(key,30);return True
            except InputError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,['journal','evidence']))
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(budget.usage,30)
        self.assertFalse(budget.can_replace('third',1))
        self.assertTrue(budget.can_replace('third',0))
