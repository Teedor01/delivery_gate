import json
import tempfile
import unittest
from pathlib import Path

from delivery_ui.checkout import SandboxCheckoutService
from delivery_ui.service import DeliveryGateService, ServiceError


class PayPalCaseAssociationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'cases.sqlite3'
        self.order = {
            'origin': 'LIVE_SANDBOX', 'order_id': 'ORDER-REAL-123', 'status': 'COMPLETED',
            'amount': '12.50', 'currency': 'USD', 'description': 'fresh order',
            'order': {'id': 'ORDER-REAL-123', 'status': 'COMPLETED', 'purchase_units': [{
                'amount': {'currency_code': 'USD', 'value': '12.50'},
                'payments': {'captures': [{'id': 'CAP-REAL-123', 'status': 'COMPLETED',
                    'amount': {'currency_code': 'USD', 'value': '12.50'},
                    'seller_protection': {'status': 'ELIGIBLE'}}]}}]},
            'capture': {'origin': 'LIVE_SANDBOX', 'order_id': 'ORDER-REAL-123', 'status': 'COMPLETED',
                'captures': [{'id': 'CAP-REAL-123', 'status': 'COMPLETED',
                    'amount': {'currency_code': 'USD', 'value': '12.50'},
                    'seller_protection': {'status': 'ELIGIBLE'}}], 'capture_response': {'id': 'ORDER-REAL-123'}}
        }

    def tearDown(self): self.tmp.cleanup()

    def test_association_persists_and_rehydrates_case(self):
        checkout = SandboxCheckoutService({}, db_path=self.db)
        checkout.orders[self.order['order_id']] = dict(self.order)
        checkout.bind_case(self.order['order_id'], 'DG-LIVE-ORDER-REAL-123')
        restored = SandboxCheckoutService({}, db_path=self.db)
        self.assertEqual(restored.get_case_id(self.order['order_id']), 'DG-LIVE-ORDER-REAL-123')
        svc = DeliveryGateService()
        st = svc.register_paypal_case(restored.get_case_id(self.order['order_id']), restored.orders[self.order['order_id']])
        self.assertEqual(st.external_paypal['order_id'], self.order['order_id'])
        self.assertEqual(st.fixture['order_ref'], self.order['order_id'])

    def test_case_rejects_mismatched_order_update(self):
        svc = DeliveryGateService()
        svc.register_paypal_case('DG-LIVE-ORDER-REAL-123', self.order)
        other = dict(self.order, order_id='ORDER-OTHER')
        with self.assertRaises(ServiceError) as ctx:
            svc.update_paypal_case('DG-LIVE-ORDER-REAL-123', other)
        self.assertEqual(ctx.exception.code, 'order_case_mismatch')

    def test_evidence_is_scoped_to_its_case(self):
        svc = DeliveryGateService()
        svc.register_paypal_case('DG-LIVE-ORDER-REAL-123', self.order)
        rec = svc.add_artifact('DG-LIVE-ORDER-REAL-123', 'Fresh carrier evidence text', 'CARRIER_EMAIL', 'test')
        self.assertIn(rec.artifact.artifact_id, svc._state('DG-LIVE-ORDER-REAL-123').artifacts)
        self.assertNotIn(rec.artifact.artifact_id, svc._state('DG-OTHER').artifacts) if 'DG-OTHER' in svc.states else None
        with self.assertRaises(Exception):
            svc.add_artifact('DG-OTHER', 'Evidence for another order', 'CARRIER_EMAIL', 'test')
        duplicate = svc.add_artifact('DG-LIVE-ORDER-REAL-123', 'Fresh carrier evidence text', 'CARRIER_EMAIL', 'duplicate')
        self.assertIs(duplicate, rec)

    def test_capture_transaction_is_visible_to_the_assessment(self):
        svc = DeliveryGateService()
        svc.register_paypal_case('DG-LIVE-ORDER-REAL-123', self.order)
        analysis = svc.analyze('DG-LIVE-ORDER-REAL-123')
        self.assertEqual(analysis.capture.capture_id, 'CAP-REAL-123')
        self.assertEqual(analysis.capture.origin, 'SANDBOX')

    def test_duplicate_case_registration_is_idempotent(self):
        svc = DeliveryGateService()
        a = svc.register_paypal_case('DG-LIVE-ORDER-REAL-123', self.order)
        b = svc.register_paypal_case('DG-LIVE-ORDER-REAL-123', self.order)
        self.assertIs(a, b)
        self.assertEqual(len([r for r in svc.refs() if r == 'DG-LIVE-ORDER-REAL-123']), 1)


if __name__ == '__main__': unittest.main()
