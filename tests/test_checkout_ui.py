import unittest
from unittest.mock import patch
from delivery_ui.checkout import SandboxCheckoutService, CheckoutError

class FakeFlow:
    def __init__(self, env, transport=None): pass
    def create(self, amount, currency, ret, cancel, description=''):
        return 201, 'dbg-create', {'id':'ORDER12345','status':'CREATED','links':[{'rel':'payer-action','href':'https://www.sandbox.paypal.com/checkoutnow?token=ORDER12345'}]}
    def status(self, oid):
        return 200, 'dbg-status', {'id':oid,'status':'APPROVED'}
    def capture(self, oid):
        return 201, 'dbg-capture', {'id':oid,'status':'COMPLETED','purchase_units':[{'payments':{'captures':[{'id':'CAPTURE12345','status':'COMPLETED','amount':{'value':'10.00','currency_code':'USD'},'seller_protection':{'status':'ELIGIBLE'}}]}}]}

class CheckoutTests(unittest.TestCase):
    def setUp(self): self.env={'PAYPAL_SANDBOX_CLIENT_ID':'id','PAYPAL_SANDBOX_CLIENT_SECRET':'secret'}
    def test_create_capture_and_duplicate_protection(self):
        with patch('delivery_ui.checkout.Flow', FakeFlow):
            svc=SandboxCheckoutService(self.env)
            rec=svc.create('10.00','USD','demo','http://localhost/live/return','http://localhost/live')
            self.assertEqual((rec['order_id'],rec['status']),('ORDER12345','CREATED'))
            self.assertEqual(rec['case_id'], 'DG-LIVE-ORDER12345')
            self.assertEqual(svc.get_case_id('ORDER12345'), rec['case_id'])
            captured=svc.capture('ORDER12345')
            self.assertEqual(captured['captures'][0]['id'],'CAPTURE12345')
            with self.assertRaisesRegex(CheckoutError,'already recorded'):
                svc.capture('ORDER12345')
    def test_refuses_unapproved_order(self):
        class NotApproved(FakeFlow):
            def status(self, oid): return 200,'dbg',{'id':oid,'status':'CREATED'}
        with patch('delivery_ui.checkout.Flow', NotApproved):
            with self.assertRaises(CheckoutError) as ctx:
                SandboxCheckoutService(self.env).capture('ORDER12345')
            self.assertEqual(ctx.exception.code,'order_not_approved')
    def test_invalid_amount_never_calls_paypal(self):
        with patch('delivery_ui.checkout.Flow', side_effect=AssertionError('must not call')):
            with self.assertRaises(CheckoutError):
                SandboxCheckoutService(self.env).create('-1','USD','x','r','c')

if __name__=='__main__': unittest.main()
