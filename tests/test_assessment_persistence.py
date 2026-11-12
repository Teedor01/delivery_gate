import tempfile
import unittest
from pathlib import Path

from delivery_ui.service import DeliveryGateService, ServiceError
from eval.corpus import ARTIFACTS


class AssessmentPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "delivery_gate.sqlite3"
        self.order = {
            "origin": "LIVE_SANDBOX", "order_id": "ORDER-PERSIST-1", "status": "COMPLETED",
            "amount": "12.50", "currency": "USD",
            "order": {"id": "ORDER-PERSIST-1", "status": "COMPLETED", "purchase_units": [{
                "amount": {"currency_code": "USD", "value": "12.50"},
                "payments": {"captures": [{"id": "CAP-PERSIST-1", "status": "COMPLETED",
                    "amount": {"currency_code": "USD", "value": "12.50"},
                    "seller_protection": {"status": "ELIGIBLE"}}]}}]},
            "capture": {"origin": "LIVE_SANDBOX", "order_id": "ORDER-PERSIST-1", "status": "COMPLETED",
                "captures": [{"id": "CAP-PERSIST-1", "status": "COMPLETED",
                    "amount": {"currency_code": "USD", "value": "12.50"},
                    "seller_protection": {"status": "ELIGIBLE"}}]}
        }

    def tearDown(self):
        self.tmp.cleanup()

    def service(self):
        return DeliveryGateService(db_path=self.db)

    def test_full_case_lifecycle_restores_after_restart(self):
        svc = self.service()
        svc.register_paypal_case("DG-LIVE-ORDER-PERSIST-1", self.order)
        artifact = ARTIFACTS[0]
        rec = svc.add_artifact("DG-LIVE-ORDER-PERSIST-1", artifact["text"], artifact["kind"], "Fresh upload test")
        svc.review_artifact("DG-LIVE-ORDER-PERSIST-1", rec.artifact.artifact_id, "reject_all", "Reviewer A", "Checked evidence")
        analysis_before = svc.analyze("DG-LIVE-ORDER-PERSIST-1")
        self.assertIsNotNone(analysis_before.assessment)
        self.assertIsNotNone(svc._state("DG-LIVE-ORDER-PERSIST-1").validation_snapshot)

        restored = self.service()
        state = restored._state("DG-LIVE-ORDER-PERSIST-1")
        self.assertEqual(state.external_paypal["order_id"], "ORDER-PERSIST-1")
        self.assertEqual(state.external_paypal["capture"]["captures"][0]["id"], "CAP-PERSIST-1")
        self.assertIn(rec.artifact.artifact_id, state.artifacts)
        self.assertTrue(state.artifacts[rec.artifact.artifact_id].result)
        self.assertTrue(state.review_log)
        self.assertTrue(state.decisions)
        self.assertIsNotNone(state.validation_snapshot)
        analysis_after = restored.analyze("DG-LIVE-ORDER-PERSIST-1")
        self.assertEqual(analysis_after.capture.capture_id, "CAP-PERSIST-1")
        self.assertEqual(len(analysis_after.state.artifacts), 1)

    def test_case_isolation_and_duplicate_evidence(self):
        svc = self.service()
        svc.register_paypal_case("DG-LIVE-ORDER-PERSIST-1", self.order)
        rec = svc.add_artifact("DG-LIVE-ORDER-PERSIST-1", "unique uploaded evidence", "OTHER", "upload")
        duplicate = svc.add_artifact("DG-LIVE-ORDER-PERSIST-1", "unique uploaded evidence", "OTHER", "retry")
        self.assertIs(rec, duplicate)
        with self.assertRaises(ServiceError):
            svc.add_artifact("DG-NOT-ASSOCIATED", "evidence must not cross cases", "OTHER", "upload")
        self.assertEqual(len(svc._state("DG-LIVE-ORDER-PERSIST-1").artifacts), 1)

    def test_order_mismatch_does_not_mutate_persisted_case(self):
        svc = self.service()
        svc.register_paypal_case("DG-LIVE-ORDER-PERSIST-1", self.order)
        mismatch = dict(self.order, order_id="ORDER-OTHER")
        with self.assertRaises(ServiceError):
            svc.update_paypal_case("DG-LIVE-ORDER-PERSIST-1", mismatch)
        restored = self.service()
        self.assertEqual(restored._state("DG-LIVE-ORDER-PERSIST-1").external_paypal["order_id"], "ORDER-PERSIST-1")


if __name__ == "__main__":
    unittest.main()
