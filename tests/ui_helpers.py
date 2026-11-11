"""Helpers for the Phase 4 UI tests."""
import json
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from delivery_extraction import bridge
from delivery_extraction.extractor import MappingExtractor, RecordedExtractor
from delivery_extraction.pipeline import run_extraction
from delivery_extraction.review import Attestation, ReviewAction, ReviewDecision
from delivery_extraction.schema import FACT_VOCAB, UNKNOWN, Artifact
from delivery_gate.engine import assess, default_registry
from delivery_gate.models import Case, EvidenceFact, Provenance, ProvStatus, SourceType, TransactionFact
from delivery_ui.server import App, make_server
from delivery_ui.service import FIXTURE_PATH, RECORDED_DIR, DeliveryGateService, default_extractor_factory
from eval.corpus import ARTIFACTS as CORPUS
from paypal_adapter import adapter as pp_adapter, disputes as pp_disputes
from paypal_adapter.handoff import merchant_jurisdiction_fact, to_case

SAMPLE = {a["id"]: a for a in CORPUS}
DOC = json.loads(Path(FIXTURE_PATH).read_text())
REFS = [t["ref"] for t in DOC["transactions"]]
FIXED = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)


def fresh(**kw):
    kw.setdefault("clock", lambda: FIXED)
    return DeliveryGateService(**kw)


CUSTOM_TEXT = "Carrier: UPS\nTracking number: 1Z999AA10123456784\nStatus: Delivered on 2026-10-27\nDelivered to: 1 Market St, San Francisco, CA 94105, US\n"


def custom_output(aid="U1", text=CUSTOM_TEXT):
    def f(i, fact, value, span, norm=None):
        return {"fact_id": f"f{i}", "fact": fact, "value": value, "normalized_value": norm or value, "source_span": span, "confidence": "HIGH", "ambiguity": False,
                "ambiguity_note": None, "attribution": "CARRIER_STATEMENT", "modality": "DIRECT", "entity_ref": None, "artifact_id": aid}
    return json.dumps({"artifact_id": aid, "extraction_notes": [], "facts": [
        f(1, "carrier_name", "UPS", "Carrier: UPS"[len("Carrier: "):]),
        f(2, "tracking_number", "1Z999AA10123456784", "Tracking number: 1Z999AA10123456784"),
        f(3, "delivery_status", "Delivered", "Status: Delivered", "DELIVERED"),
    ]})


def injected_factory(outputs):
    """Extractor factory that serves canned model outputs for non-sample text (and recorded outputs for samples)."""
    def factory(artifact, recognized):
        if recognized:
            return RecordedExtractor(RECORDED_DIR), RecordedExtractor.KIND, None
        return MappingExtractor(outputs), MappingExtractor.KIND, None
    return factory


# ---- independent oracle: the same payment, rebuilt from the Phase 1-3 public APIs without the service -------------------------------------------------
def independent_assessment(ref, answers_override=None):
    fx = next(t for t in DOC["transactions"] if t["ref"] == ref)
    cap = pp_adapter.observe_order(fx["paypal_order"], origin="FIXTURE").select_capture()
    disp = pp_disputes.observe_dispute(fx["paypal_dispute"], origin="FIXTURE") if fx.get("paypal_dispute") else None
    h = to_case(cap, case_id=ref, dispute=disp, merchant_country=merchant_jurisdiction_fact(fx["merchant_provided"]["country"], source_ref=f"merchant:{ref}"))
    mp = fx["merchant_provided"]
    mref = f"merchant:{ref}"
    prov = Provenance(SourceType.MERCHANT_INPUT, mref, ProvStatus.MERCHANT_ASSERTED)
    facts = list(h.case.transaction_facts) + [TransactionFact("physical_goods", mp["physical_goods"], prov),
                                              TransactionFact("pre_order_or_made_to_order", mp["pre_order_or_made_to_order"], prov),
                                              TransactionFact("transaction_details_address", dict(mp["transaction_details_address"]), prov)]
    answers = answers_override or mp["answers"]
    evidence = [EvidenceFact(k, v, prov) for k, v in sorted(answers.items()) if v is not None]
    base = Case(ref, tuple(facts), tuple(evidence))
    arts, cands, decisions, atts = {}, [], [], []
    for a in fx["artifacts"]:
        s = SAMPLE[a["artifact_id"]]
        art = Artifact(s["id"], s["text"], s["kind"])
        arts[art.artifact_id] = art
        res = run_extraction([art], RecordedExtractor(RECORDED_DIR)).results[0]
        cands += res.report.accepted
        r = a.get("review")
        if not r:
            continue
        usable = [f for f in res.report.accepted if FACT_VOCAB[f.fact]["engine"] and f.normalized_value != UNKNOWN]
        if r["mode"] == "attest_carrier":
            atts.append(Attestation(art.artifact_id, r["reviewer"]))
            decisions += [ReviewDecision(f.fact_id, ReviewAction.APPROVE_AS_CARRIER_DOCUMENT, r["reviewer"]) for f in usable
                          if f.attribution in ("CARRIER_STATEMENT", "UNKNOWN") and f.modality == "DIRECT"]
        elif r["mode"] == "approve_merchant":
            decisions += [ReviewDecision(f.fact_id, ReviewAction.APPROVE_AS_MERCHANT_ASSERTION, r["reviewer"]) for f in usable]
    br = bridge.build_case(base, cands, arts, decisions, atts)
    return assess(default_registry(), br.case)


# ---- html helpers ------------------------------------------------------------------------------------------------------------------------------------
def visible(html: str) -> str:
    """Readable text of a page with entities decoded (flash messages are HTML-escaped)."""
    import html as H
    return H.unescape(text_of(html))


def text_of(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class Balance(HTMLParser):
    VOID = {"meta", "link", "input", "br", "img", "hr", "path", "circle", "rect"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()


def balance_errors(html: str):
    p = Balance()
    p.feed(html)
    return p.errors + [f"unclosed <{t}>" for t in p.stack if t not in ("html", "body")]


def get(app, path):
    st, h, b = app.handle("GET", path)
    return st, h, b.decode("utf-8")


def post(app, path, fields=None, json_body=None):
    if json_body is not None:
        return app.handle("POST", path, json.dumps(json_body).encode(), "application/json")
    from urllib.parse import urlencode
    return app.handle("POST", path, urlencode(fields or {}).encode(), "application/x-www-form-urlencoded")


def follow(app, resp):
    st, h, b = resp
    if st == 303:
        return get(app, h["Location"])
    return st, h, b.decode()


class LiveServer:
    """A real http.server on an ephemeral port, for socket-level tests."""
    def __init__(self, service=None):
        self.srv = make_server(service or fresh(), port=0)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def request(self, method, path, data=None, headers=None):
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
