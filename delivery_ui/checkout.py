from __future__ import annotations
import os
import json
import sqlite3
import tempfile
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional
from tools.sandbox_order_flow import Flow
from paypal_adapter.sandbox_client import SandboxConfigError, SandboxRequestError

class CheckoutError(Exception):
    def __init__(self, code: str, message: str, status: Optional[int] = None, debug_id: Optional[str] = None):
        super().__init__(message); self.code, self.status, self.debug_id = code, status, debug_id

class SandboxCheckoutService:
    def __init__(self, env: Optional[Mapping[str,str]] = None, transport=None, db_path=None):
        self.env = os.environ if env is None else env
        self.transport = transport
        configured_db = db_path or self.env.get("DELIVERY_GATE_CASE_DB")
        if configured_db:
            self.db_path = Path(configured_db)
        elif env is not None:
            self.db_path = Path(tempfile.mkstemp(prefix="delivery-gate-test-", suffix=".sqlite3")[1])
        else:
            self.db_path = Path(__file__).resolve().parent.parent / "data" / "paypal_cases.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.orders: Dict[str, Dict[str,Any]] = {}
        self.captures: Dict[str, Dict[str,Any]] = {}
        self._load_orders()

    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self):
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS paypal_cases (order_id TEXT PRIMARY KEY, case_id TEXT UNIQUE, record_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    def _load_orders(self):
        with self._connect() as db:
            for row in db.execute("SELECT record_json FROM paypal_cases"):
                rec = json.loads(row["record_json"])
                self.orders[rec["order_id"]] = rec
                if rec.get("capture"):
                    self.captures[rec["order_id"]] = rec["capture"]

    def bind_case(self, order_id: str, case_id: str):
        rec = self.orders.get(order_id)
        if rec is None: raise CheckoutError("order_not_found", "Create the PayPal order through this application first.")
        existing = self.get_case_id(order_id)
        if existing and existing != case_id: raise CheckoutError("case_conflict", "This PayPal order is already associated with another assessment.")
        rec["case_id"] = case_id
        with self._connect() as db:
            db.execute("INSERT INTO paypal_cases(order_id,case_id,record_json) VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET record_json=excluded.record_json, updated_at=CURRENT_TIMESTAMP", (order_id, case_id, json.dumps(rec)))
        return rec

    def get_case_id(self, order_id: str):
        with self._connect() as db:
            row = db.execute("SELECT case_id FROM paypal_cases WHERE order_id=?", (order_id,)).fetchone()
        return row["case_id"] if row else None

    def _persist(self, order_id: str):
        rec = self.orders.get(order_id)
        if not rec: return
        with self._connect() as db:
            db.execute("UPDATE paypal_cases SET record_json=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (json.dumps(rec), order_id))

    def configured(self):
        return bool((self.env.get('PAYPAL_SANDBOX_CLIENT_ID') or '').strip() and (self.env.get('PAYPAL_SANDBOX_CLIENT_SECRET') or '').strip())

    def _flow(self):
        try: return Flow(self.env, self.transport)
        except SandboxConfigError as e: raise CheckoutError('not_configured', str(e)) from None

    def create(self, amount: str, currency: str, description: str, return_url: str, cancel_url: str):
        try: value = Decimal(amount)
        except (InvalidOperation, TypeError): raise CheckoutError('invalid_amount','Enter a valid positive amount.') from None
        if not value.is_finite() or value <= 0 or value > Decimal('1000000') or value.as_tuple().exponent < -2:
            raise CheckoutError('invalid_amount','Amount must be positive and have no more than two decimal places.')
        currency = (currency or 'USD').upper()
        if len(currency) != 3 or not currency.isalpha(): raise CheckoutError('invalid_currency','Enter a three-letter currency code.')
        try: status, debug, data = self._flow().create(format(value, '.2f'), currency, return_url, cancel_url, description)
        except SandboxRequestError as e: raise CheckoutError('paypal_request_failed',str(e),e.status,e.debug_id) from None
        if status not in (200,201) or not data.get('id'): raise CheckoutError('paypal_create_failed',str(data.get('message') or 'PayPal did not create the order.'),status,debug)
        links = data.get('links') or []
        approval = next((x.get('href') for x in links if x.get('rel') in ('payer-action','approve') and x.get('href')),None)
        case_id = 'DG-LIVE-' + ''.join(ch for ch in data['id'] if ch.isalnum() or ch in '_-')
        rec = {'origin':'LIVE_SANDBOX','order':data,'order_id':data['id'],'case_id':case_id,'status':data.get('status'),'amount':format(value,'.2f'),'currency':currency,'description':description[:127], 'approval_url':approval,'http_status':status,'paypal_debug_id':debug}
        self.orders[data['id']] = rec
        # Persist the stable association in the same write as the order record. If the
        # process stops before assessment registration, App startup can rehydrate it.
        with self._connect() as db:
            db.execute("INSERT INTO paypal_cases(order_id,case_id,record_json) VALUES(?,?,?)", (data['id'], case_id, json.dumps(rec)))
        return rec

    def retrieve(self, order_id: str):
        try: status, debug, data = self._flow().status(order_id)
        except (SandboxRequestError, SandboxConfigError) as e: raise CheckoutError('paypal_retrieval_failed',str(e),getattr(e,'status',None),getattr(e,'debug_id',None)) from None
        if status != 200: raise CheckoutError('paypal_retrieval_failed',str(data.get('message') or 'PayPal could not retrieve the order.'),status,debug)
        rec = {'origin':'LIVE_SANDBOX','order':data,'order_id':data.get('id'),'status':data.get('status'),'http_status':status,'paypal_debug_id':debug}
        if data.get('id') in self.orders:
            self.orders[data['id']].update({'order':data,'status':data.get('status')})
            self._persist(data['id'])
        return rec

    def capture(self, order_id: str):
        if order_id in self.captures:
            raise CheckoutError('already_captured','A capture was already recorded for this order; no second capture was attempted.')
        current = self.retrieve(order_id)
        state = current.get('status')
        if state == 'COMPLETED': raise CheckoutError('already_captured','PayPal reports this order is already completed; no second capture was attempted.')
        if state != 'APPROVED': raise CheckoutError('order_not_approved',f'PayPal order status is {state or "unknown"}; approve it before capture.')
        try: status, debug, data = self._flow().capture(order_id)
        except SandboxRequestError as e: raise CheckoutError('paypal_capture_failed',str(e),e.status,e.debug_id) from None
        if status not in (200,201): raise CheckoutError('paypal_capture_failed',str(data.get('message') or 'PayPal did not confirm capture.'),status,debug)
        captures = [c for pu in data.get('purchase_units',[]) for c in (pu.get('payments',{}).get('captures',[]) or [])]
        result = {'origin':'LIVE_SANDBOX','order_id':order_id,'status':data.get('status'),'capture_response':data,'captures':captures,'http_status':status,'paypal_debug_id':debug}
        self.captures[order_id] = result
        if order_id in self.orders:
            self.orders[order_id].update({'status':data.get('status'),'capture':result,'order':data})
            self._persist(order_id)
        return result
