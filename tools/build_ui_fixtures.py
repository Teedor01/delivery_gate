import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "delivery_ui" / "fixtures" / "transactions.json"
TD = {"line1": "1 Market St", "city": "San Francisco", "region": "CA", "postal_code": "94105", "country": "US"}
ADDR_API = {"address_line_1": "1 Market St", "admin_area_2": "San Francisco", "admin_area_1": "CA", "postal_code": "94105", "country_code": "US"}
ANSWERS_OK = {"redirect_detected": False, "response_to_paypal": "NO_REQUEST_OUTSTANDING", "shipped_after_advised_not_to_release": False}


def order(n, amount, created, sp_status="ELIGIBLE", cats=("ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION"), cstatus="COMPLETED"):
    cid = f"FXCAP{n}"
    sp = None if sp_status is None else {"status": sp_status, **({"dispute_categories": list(cats)} if cats else {})}
    cap = {"id": cid, "status": cstatus, "amount": {"currency_code": "USD", "value": amount}, "final_capture": True,
           "create_time": created, "update_time": created}
    if sp:
        cap["seller_protection"] = sp
    return {"id": f"FXORDER{n}", "status": "COMPLETED",
            "payment_source": {"paypal": {"account_id": "FXPAYER1", "account_status": "VERIFIED"}},
            "purchase_units": [{"reference_id": "default", "shipping": {"name": {"full_name": "Test Buyer"}, "address": ADDR_API},
                                "payments": {"captures": [cap]}}]}


def dispute(n, reason, channel="INTERNAL", stage="INQUIRY", amount=None, created="2026-10-25T08:00:00Z", gross=None):
    d = {"dispute_id": f"PP-D-FX{n}", "create_time": created, "update_time": created,
         "disputed_transactions": [{"seller_transaction_id": f"FXCAP{n}", "gross_amount": {"currency_code": "USD", "value": gross},
                                    "seller": {"merchant_id": "FXMERCHANT1"}}],
         "reason": reason, "status": "WAITING_FOR_SELLER_RESPONSE", "dispute_state": "REQUIRED_ACTION",
         "dispute_life_cycle_stage": stage, "dispute_channel": channel}
    if amount:
        d["dispute_amount"] = {"currency_code": "USD", "value": amount}
    return d


def tx(ref, n, order_ref, amount, created, *, scenarios, title, summary, sp="ELIGIBLE", cats=("ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION"),
       cstatus="COMPLETED", disp=None, artifacts=(), suggested=(), answers=ANSWERS_OK):
    return {"ref": ref, "order_ref": order_ref, "scenarios": list(scenarios), "scenario_title": title, "scenario_summary": summary,
            "paypal_order": order(n, amount, created, sp, cats, cstatus), "paypal_dispute": disp,
            "merchant_provided": {"country": "US", "physical_goods": True, "pre_order_or_made_to_order": False, "transaction_details_address": TD,
                                  "answers": dict(answers)},
            "artifacts": list(artifacts), "suggested_evidence": list(suggested)}


def art(aid, source, added, review=None):
    return {"artifact_id": aid, "source_label": source, "added_at": added, "review": review}


DEMO_REVIEWER = "Demo reviewer (fixture)"
T = [
    tx("DG-20481", "20481", "Order #1048", "480.00", "2026-10-14T14:32:00Z", scenarios=[2, 6], title="Missing delivery evidence, then a counterfactual",
       summary="The customer says the item never arrived. The only evidence on file is a note with no carrier details, so nothing demonstrates delivery. "
               "Use What changes? to see what a carrier delivery record would change.",
       disp=dispute("20481", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", amount="480.00", gross="480.00", created="2026-10-24T09:12:00Z"),
       artifacts=[art("A11", "Pasted text", "2026-10-25T10:05:00Z")],
       suggested=[{"artifact_id": "A01", "label": "Carrier delivery email (sample FedEx notification)"}]),
    tx("DG-20479", "20479", "Order #1046", "129.00", "2026-10-13T11:02:00Z", scenarios=[1], title="Clean carrier evidence",
       summary="A carrier delivery email was added and a reviewer attested that the document itself is genuine. The modeled requirements are demonstrated; PayPal decides.",
       disp=dispute("20479", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", amount="129.00", gross="129.00", created="2026-10-23T15:40:00Z"),
       artifacts=[art("A01", "Uploaded file: fedex-delivery-notice.txt", "2026-10-24T08:30:00Z",
                      {"mode": "attest_carrier", "reviewer": DEMO_REVIEWER, "at": "2026-10-24T08:45:00Z"})]),
    tx("DG-20472", "20472", "Order #1039", "760.00", "2026-10-12T16:20:00Z", scenarios=[3], title="Conflicting addresses",
       summary="Two carrier records disagree about where the package went. The conflict is shown, not resolved: a person has to check it.",
       disp=dispute("20472", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", amount="320.00", gross="760.00", created="2026-10-26T13:05:00Z"),
       artifacts=[art("A08", "Pasted text", "2026-10-26T14:00:00Z", {"mode": "attest_carrier", "reviewer": DEMO_REVIEWER, "at": "2026-10-26T14:10:00Z"}),
                  art("A09", "Pasted text", "2026-10-26T14:02:00Z", {"mode": "attest_carrier", "reviewer": DEMO_REVIEWER, "at": "2026-10-26T14:11:00Z"})]),
    tx("DG-20475", "20475", "Order #A-1042", "215.00", "2026-10-15T09:44:00Z", scenarios=[4], title="Merchant assertion",
       summary="The merchant's own message gives a tracking number and dates. It can be recorded as the merchant's statement, but it cannot stand in for a carrier document.",
       disp=dispute("20475", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", amount="215.00", gross="215.00", created="2026-10-25T17:30:00Z"),
       artifacts=[art("A04", "Pasted text", "2026-10-26T09:00:00Z", {"mode": "approve_merchant", "reviewer": DEMO_REVIEWER, "at": "2026-10-26T09:05:00Z"})]),
    tx("DG-20468", "20468", "Order #1035", "84.50", "2026-10-11T10:15:00Z", scenarios=[5], title="Unknown PayPal status",
       summary="An unauthorized-payment claim. PayPal reports a protection status, but how that value relates to the policy condition is not established, so the result stays unresolved.",
       sp="PARTIALLY_ELIGIBLE", cats=("ITEM_NOT_RECEIVED",),
       disp=dispute("20468", "UNAUTHORISED", amount="84.50", gross="84.50", created="2026-10-27T08:20:00Z"),
       artifacts=[art("A01", "Pasted text", "2026-10-27T09:00:00Z", {"mode": "attest_carrier", "reviewer": DEMO_REVIEWER, "at": "2026-10-27T09:05:00Z"})]),
    tx("DG-20463", "20463", "Order #1031", "312.00", "2026-10-10T13:50:00Z", scenarios=[], title="Card-issuer or bank dispute (route unknown)",
       summary="The customer went to their card issuer or bank. PayPal documents that this channel includes both chargebacks and ACH returns, so the dispute route stays unknown.",
       cstatus="PARTIALLY_REFUNDED",
       disp=dispute("20463", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", channel="EXTERNAL", stage="CHARGEBACK", amount="312.00", gross="312.00", created="2026-10-27T12:00:00Z"),
       artifacts=[art("A01", "Pasted text", "2026-10-27T12:30:00Z", {"mode": "attest_carrier", "reviewer": DEMO_REVIEWER, "at": "2026-10-27T12:35:00Z"})]),
    tx("DG-20460", "20460", "Order #1029", "58.00", "2026-10-09T09:05:00Z", scenarios=[], title="Not-as-described reason (not normalised)",
       summary="PayPal's reason is 'not as described'. Delivery Gate keeps the raw reason but does not map it to a claim category, so no rule is selected.",
       disp=dispute("20460", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", amount="58.00", gross="58.00", created="2026-10-28T10:00:00Z")),
    tx("DG-20455", "20455", "Order #1024", "59.99", "2026-10-08T18:30:00Z", scenarios=[], title="No dispute reported",
       summary="A completed payment with no dispute. There is nothing to assess until a dispute exists."),
]
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"_note": "Synthetic demo fixtures. PayPal responses are hand-written from documented shapes and are NOT live PayPal data.",
                           "merchant": {"name": "Demo merchant", "country": "US"}, "transactions": T}, indent=1, sort_keys=True) + "\n")
print("wrote", OUT, len(T), "transactions")
