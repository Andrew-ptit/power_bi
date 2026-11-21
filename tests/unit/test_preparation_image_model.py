import copy
import unittest
from pbip_assistant.sources.preparation.image_model import preservation_fingerprint,image_full_fingerprint

class PreservationImageTests(unittest.TestCase):
    def image(self):
        return {"version":1,"sheets":[{"sheetId":"native","name":"Data","rowOffset":0,"columnOffset":0,"values":[["a"]],"formulas":[["a"]],"formulaCells":[],"numberFormats":[["General"]]}],"preservation":{"version":1,"packageFingerprint":"sha256:"+"1"*64,"evidenceId":"server-owned"}}
    def test_native_id_and_evidence_id_are_independent_of_content_hash(self):
        image=self.image();expected=preservation_fingerprint(image)
        image["sheets"][0]["sheetId"]="other";image["preservation"]["evidenceId"]="other-owned"
        self.assertEqual(expected,preservation_fingerprint(image))
    def test_package_and_semantic_edits_change_complete_hash(self):
        image=self.image();expected=preservation_fingerprint(image)
        changed=copy.deepcopy(image);changed["preservation"]["packageFingerprint"]="sha256:"+"2"*64
        self.assertNotEqual(expected,preservation_fingerprint(changed))
        changed=copy.deepcopy(image);changed["sheets"][0]["values"][0][0]="b"
        self.assertNotEqual(expected,preservation_fingerprint(changed))
    def test_corrupted_or_missing_evidence_fails(self):
        image=self.image();image["fullFingerprint"]="sha256:"+"0"*64
        with self.assertRaises(Exception):preservation_fingerprint(image)
        del image["preservation"]
        with self.assertRaises(Exception):preservation_fingerprint(image)
