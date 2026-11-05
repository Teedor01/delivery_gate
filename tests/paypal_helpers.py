import copy, json, re
from pathlib import Path
from delivery_gate.engine import assess, default_registry
from delivery_gate.models import Case, Provenance, ProvStatus, SourceType, TransactionFact
from delivery_gate import samples as S
from paypal_adapter import adapter, handoff as hmod

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures" / "paypal"
REG = default_registry()
CATEGORIES = {"UNAUTHORIZED_TRANSACTION": S.unauth_evidence, "ITEM_NOT_RECEIVED": S.inr_evidence, "SIGNIFICANTLY_NOT_AS_DESCRIBED": lambda: ()}


def wrapper(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def response(name):
    return copy.deepcopy(wrapper(name)["response"])


def observe(resp, **kw):
    return adapter.observe_order(resp, origin="FIXTURE", **kw)


def handoff(resp, **kw):
    return hmod.to_case(observe(resp, **kw).select_capture())


def at_path(resp, path):
    """Resolve 'purchase_units[0].payments.captures[0].amount.value' inside a response."""
    cur = resp
    for part in path.split("."):
        m = re.match(r"^(\w+)\[(\d+)\]$", part)
        cur = cur[m.group(1)][int(m.group(2))] if m else cur[part]
    return cur


def merchant_fact(name, value):
    return TransactionFact(name, value, Provenance(SourceType.MERCHANT_INPUT, "fixture:merchant-config", ProvStatus.MERCHANT_ASSERTED))


def full_case(h, category, route="PAYPAL_DISPUTE"):
    """The PayPal-derived facts plus the facts PayPal's capture does NOT expose, supplied under explicit MERCHANT provenance."""
    extra = [merchant_fact("merchant_account_country", "US"), merchant_fact("claim_category", category),
             merchant_fact("route", route), merchant_fact("physical_goods", True),
             merchant_fact("pre_order_or_made_to_order", False), merchant_fact("transaction_details_address", S.TD_ADDR)]
    return Case(h.case.case_id, h.case.transaction_facts + tuple(extra), tuple(CATEGORIES[category]()))


def assessment(resp, category, route="PAYPAL_DISPUTE"):
    return assess(REG, full_case(handoff(resp), category, route))


def policy_view(a, token=None):
    """The assessment minus the verbatim echo of the observed token. Everything left is policy-relevant."""
    d = a.core_dict()
    if token is not None:
        for c in d["policy_conditions"]:
            c["observed_value"] = "<token>"
        if "paypal_seller_protection_status" in d["observed_inputs"] and d["observed_inputs"]["paypal_seller_protection_status"]["value"] is not None:
            d["observed_inputs"]["paypal_seller_protection_status"]["value"] = "<token>"
        d["explanation"] = [e.replace(repr(token), "<token>") for e in d["explanation"]]
    return d


SP_STATUS_PATH = "purchase_units[0].payments.captures[0].seller_protection.status"


def with_status(resp, token):
    r = copy.deepcopy(resp)
    r["purchase_units"][0]["payments"]["captures"][0]["seller_protection"]["status"] = token
    return r
