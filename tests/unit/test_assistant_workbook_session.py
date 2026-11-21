from copy import deepcopy
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_session import AssistantSessionStore


class AssistantWorkbookSessionTests(unittest.TestCase):
    def setUp(self):
        self.store = AssistantSessionStore()
        self.addCleanup(self.store.close)

    def test_workbook_session_needs_no_directory_and_retains_normal_analysis(self):
        state = self.store.bind_workbook()
        self.assertEqual(state['rootLabel'], 'Workbook')
        request = {'kind': 'workbook', 'mode': 'compute', 'payload': {
            'name': 'Orders', 'origin': 'Workbook!Orders!Orders', 'sheet': 'Orders',
            'table': False, 'header': ['Order', 'Amount'], 'rows': [['A', '10'], ['B', '20']],
            'sampleOrdinals': [0, 1], 'totalRows': 2}}
        original = deepcopy(request)
        result = self.store.ingest([request])
        self.assertEqual(result['snapshot']['tables'][0]['rowCount'], 2)
        self.assertEqual(request, original)
        self.assertTrue(self.store.understand()['understand'])

    def test_workbook_session_rejects_file_sources_before_resolution(self):
        self.store.bind_workbook()
        with self.assertRaises(InputError) as caught:
            self.store.ingest([{'kind': 'csv', 'path': 'private.csv', 'options': {}, 'mode': 'compute'}])
        self.assertEqual(caught.exception.code, 'ASSISTANT_WORKBOOK_REQUIRED')
        self.assertIsNone(self.store.state()['snapshotHash'])
        self.store.reset()
        with self.assertRaises(InputError) as caught:
            self.store.ingest([{'kind': 'workbook', 'mode': 'compute', 'payload': {}}])
        self.assertEqual(caught.exception.code, 'AF_STAGE_INVALID')
