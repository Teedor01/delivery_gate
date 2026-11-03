import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delivery_extraction.prompt import PROMPT_SHA256

OUT = Path(__file__).resolve().parent / "recorded_outputs"
OUT.mkdir(exist_ok=True)


def F(i, fact, value, nv, span, att, mod="DIRECT", amb=False, note=None, ent=None, conf="HIGH"):
    return {"fact_id": i, "fact": fact, "value": value, "normalized_value": nv, "source_span": span, "confidence": conf,
            "ambiguity": amb, "ambiguity_note": note, "attribution": att, "modality": mod, "entity_ref": ent}


def out(aid, facts, notes=()):
    for f in facts:
        f["artifact_id"] = aid
    (OUT / f"{aid}.json").write_text(json.dumps({"artifact_id": aid, "facts": facts, "extraction_notes": list(notes)}, indent=2, ensure_ascii=False))


C, M, U, CU = "CARRIER_STATEMENT", "MERCHANT_STATEMENT", "UNKNOWN", "CUSTOMER_STATEMENT_RELAYED"

out("A01", [
    F("f1", "tracking_number", "774912340001", "774912340001", "Tracking number: 774912340001", C),
    F("f2", "carrier_name", "FedEx", "FedEx", "FedEx Delivery Manager", C),
    F("f3", "delivery_status", "was delivered", "DELIVERED", "Your package was delivered", C),
    F("f4", "delivery_date", "Tuesday, October 20, 2026", "2026-10-20", "Delivered: Tuesday, October 20, 2026 at 2:32 PM", C),
    F("f5", "delivery_time", "2:32 PM", "14:32", "Delivered: Tuesday, October 20, 2026 at 2:32 PM", C),
    F("f6", "recipient_address", "1 Market St, San Francisco, CA 94105, US",
      {"line1": "1 Market St", "city": "San Francisco", "region": "CA", "postal_code": "94105", "country": "US"},
      "Delivered to: 1 Market St, San Francisco, CA 94105, US", C),
    F("f7", "signature_present", "Signed for by: A. SMITH", True, "Signed for by: A. SMITH", C),
])
out("A02", [
    F("f1", "tracking_number", "1Z999AA10123456784", "1Z999AA10123456784", "pkg 1Z999AA10123456784", C),
    F("f2", "carrier_name", "ups", "UPS", "ups  quantum view notif", C, conf="MEDIUM"),
    F("f3", "delivery_status", "DELIVERED", "DELIVERED", "-- DELIVERED --", C),
    F("f4", "delivery_date", "10/20/2026", "2026-10-20", "10/20/2026", C),
    F("f5", "recipient_address", "1 MARKET ST  SAN FRANCISCO CA 94105-1234",
      {"line1": "1 MARKET ST", "city": "SAN FRANCISCO", "region": "CA", "postal_code": "94105-1234"},
      "1 MARKET ST  SAN FRANCISCO CA 94105-1234", C, conf="MEDIUM"),
], ["Text is irregularly spaced and upper-cased; values were copied as written."])
out("A03", [
    F("f1", "tracking_number", "1Z999AA10123456785", "1Z999AA10123456785", "Tracking ID: 1Z999AA10123456785", U),
    F("f2", "delivery_status", "Delivered", "DELIVERED", "Status: Delivered", U),
    F("f3", "delivery_date", "Oct 20, 2026", "2026-10-20", "Delivery date: Oct 20, 2026 2:32 PM", U),
    F("f4", "delivery_time", "2:32 PM", "14:32", "Delivery date: Oct 20, 2026 2:32 PM", U),
    F("f5", "recipient_address", "1 Market St, San Francisco", {"line1": "1 Market St", "city": "San Francisco"},
      "Delivered to 1 Market St, San Francisco", U),
], ["No sender or carrier is named in the artifact, so attribution is UNKNOWN and no carrier_name is output."])
out("A04", [
    F("f1", "order_reference", "#A-1042", "A-1042", "order #A-1042", M),
    F("f2", "shipment_date", "Oct 15", "UNKNOWN", "shipped order #A-1042 on Oct 15", M, amb=True, note="Month and day only; the artifact gives no year."),
    F("f3", "carrier_name", "UPS", "UPS", "via UPS", M),
    F("f4", "tracking_number", "1Z999AA10123456786", "1Z999AA10123456786", "tracking 1Z999AA10123456786", M),
    F("f5", "delivery_status", "was delivered", "DELIVERED", "The tracking page shows it was delivered Oct 19", M, mod="REPORTED"),
    F("f6", "delivery_date", "Oct 19", "UNKNOWN", "it was delivered Oct 19", M, mod="REPORTED", amb=True, note="Month and day only; the artifact gives no year."),
])
out("A05", [
    F("f1", "carrier_name", "FedEx", "FedEx", "FedEx 774912340003", M),
    F("f2", "tracking_number", "774912340003", "774912340003", "FedEx 774912340003", M),
    F("f3", "delivery_status", "delivered", "DELIVERED", "delivered to 1 Market Street on Oct 20, 2026", M),
    F("f4", "delivery_date", "Oct 20, 2026", "2026-10-20", "on Oct 20, 2026", M),
    F("f5", "recipient_address", "1 Market Street", {"line1": "1 Market Street"}, "delivered to 1 Market Street", M),
], ["A second address in the artifact is described as a billing address; the vocabulary has no billing-address fact, so it was not extracted."])
out("A06", [
    F("f1", "delivery_status", "has been delivered", "DELIVERED", "Your order has been delivered", U),
    F("f2", "delivery_date", "Oct 20, 2026", "2026-10-20", "Delivered Oct 20, 2026", U),
    F("f3", "recipient_address", "1 Market St, San Francisco, CA 94105",
      {"line1": "1 Market St", "city": "San Francisco", "region": "CA", "postal_code": "94105"},
      "1 Market St, San Francisco, CA 94105", U),
], ["The artifact contains no tracking number; none was output."])
out("A07", [
    F("f1", "carrier_name", "FedEx", "FedEx", "FedEx tracking", M),
    F("f2", "tracking_number", "774912340002", "774912340002", "tracking 774912340002", M),
    F("f3", "delivery_status", "delivered", "DELIVERED", "says delivered Tuesday at 14:32 to 1 Market Street", M, mod="REPORTED"),
    F("f4", "delivery_date", "Tuesday", "UNKNOWN", "delivered Tuesday at 14:32", M, mod="REPORTED", amb=True, note="Weekday only; the artifact gives no calendar date."),
    F("f5", "delivery_time", "14:32", "14:32", "Tuesday at 14:32", M, mod="REPORTED"),
    F("f6", "recipient_address", "1 Market Street", {"line1": "1 Market Street"}, "to 1 Market Street", M, mod="REPORTED"),
    F("f7", "signature_present", "Nobody signed for it", False, "Nobody signed for it", M),
    F("f8", "intended_ship_to_address", "1 Market St", {"line1": "1 Market St"}, "The order was supposed to go to 1 Market St", M),
])
out("A08", [
    F("f1", "delivery_status", "Delivered", "DELIVERED", "Delivered to 1 Market Street, San Francisco, CA 94105 on Oct 20, 2026", U),
    F("f2", "recipient_address", "1 Market Street, San Francisco, CA 94105",
      {"line1": "1 Market Street", "city": "San Francisco", "region": "CA", "postal_code": "94105"},
      "1 Market Street, San Francisco, CA 94105", U),
    F("f3", "delivery_date", "Oct 20, 2026", "2026-10-20", "CA 94105 on Oct 20, 2026", U),
    F("f4", "tracking_number", "1Z999AA10123456787", "1Z999AA10123456787", "Tracking 1Z999AA10123456787", U),
])
out("A09", [
    F("f1", "tracking_number", "1Z999AA10123456787", "1Z999AA10123456787", "shipment 1Z999AA10123456787", U),
    F("f2", "redirect_reported", "was redirected", True, "was redirected to 22 Broad Street, New York, NY 10004 by the recipient on Oct 21, 2026", U),
    F("f3", "recipient_address", "22 Broad Street, New York, NY 10004",
      {"line1": "22 Broad Street", "city": "New York", "region": "NY", "postal_code": "10004"},
      "22 Broad Street, New York, NY 10004", U, note="Address the shipment was redirected to."),
])
out("A10", [], ["No shipment or delivery facts are stated in this artifact."])
out("A11", [
    F("f1", "delivery_status", "probably delivered", "UNKNOWN", "Looks like it was probably delivered", M, mod="HEDGED", amb=True,
      note="Hedged: 'looks like' and 'probably'; the artifact does not state that delivery occurred.", conf="HIGH"),
], ["Other sentences in the artifact are opinions about an outcome, not shipment facts, and were not extracted."])
out("A12", [
    F("f1", "order_reference", "A-2001", "A-2001", "Order A-2001", M, ent="A-2001"),
    F("f2", "carrier_name", "UPS", "UPS", "Order A-2001: UPS", M, ent="A-2001"),
    F("f3", "tracking_number", "1Z999AA10123456788", "1Z999AA10123456788", "UPS 1Z999AA10123456788", M, ent="A-2001"),
    F("f4", "delivery_status", "delivered", "DELIVERED", "delivered Oct 19, 2026 to 5 Pine St, Portland, OR 97204", M, ent="A-2001"),
    F("f5", "delivery_date", "Oct 19, 2026", "2026-10-19", "delivered Oct 19, 2026", M, ent="A-2001"),
    F("f6", "recipient_address", "5 Pine St, Portland, OR 97204", {"line1": "5 Pine St", "city": "Portland", "region": "OR", "postal_code": "97204"},
      "5 Pine St, Portland, OR 97204", M, ent="A-2001"),
    F("f7", "order_reference", "A-2002", "A-2002", "Order A-2002", M, ent="A-2002"),
    F("f8", "carrier_name", "UPS", "UPS", "Order A-2002: UPS", M, ent="A-2002"),
    F("f9", "tracking_number", "1Z999AA10123456789", "1Z999AA10123456789", "UPS 1Z999AA10123456789", M, ent="A-2002"),
    F("f10", "delivery_status", "still in transit", "IN_TRANSIT", "is still in transit", M, ent="A-2002"),
], ["The artifact describes two orders; facts carry entity_ref."])
out("A13", [
    F("f1", "redirect_reported", "it wasn't redirected", False, "The customer says it wasn't redirected", CU, mod="REPORTED"),
    F("f2", "delivery_status", "delivered", "DELIVERED", "Carrier tracking shows delivered Oct 20, 2026 to 1 Market St, San Francisco, CA 94105", M, mod="REPORTED"),
    F("f3", "delivery_date", "Oct 20, 2026", "2026-10-20", "delivered Oct 20, 2026", M, mod="REPORTED"),
    F("f4", "recipient_address", "1 Market St, San Francisco, CA 94105",
      {"line1": "1 Market St", "city": "San Francisco", "region": "CA", "postal_code": "94105"},
      "1 Market St, San Francisco, CA 94105", M, mod="REPORTED"),
], ["The redirect statement is a customer's claim relayed by the writer, not a carrier statement."])
out("A14", [
    F("f1", "delivery_status", "Delivered", "DELIVERED", "Delivered to 1 Market St Oct 20 2026", U),
    F("f2", "delivery_date", "Oct 20 2026", "2026-10-20", "Oct 20 2026", U),
    F("f3", "recipient_address", "1 Market St", {"line1": "1 Market St"}, "Delivered to 1 Market St Oct 20 2026", U),
], ["Instruction-like text inside the artifact was treated as data and was not followed."])
out("A15", [
    F("f1", "tracking_number", "1Z999AA10123456790", "UNKNOWN", "I think the tracking number is 1Z999AA10123456790 but I'm not sure", M,
      mod="HEDGED", amb=True, note="The writer is not sure of the number; the raw value is kept but not normalized.", conf="MEDIUM"),
    F("f2", "delivery_status", "got there", "UNKNOWN", "It got there around the 20th I guess", M, mod="HEDGED", amb=True,
      note="Hedged and does not state a delivery status."),
    F("f3", "delivery_date", "around the 20th", "UNKNOWN", "around the 20th I guess", M, mod="HEDGED", amb=True,
      note="Approximate day only; no month or year."),
])
(OUT / "MANIFEST.json").write_text(json.dumps({
    "produced_by": "the assistant (Claude) in the build conversation, following delivery_extraction/prompt.py; transcribed by eval/author_recorded_outputs.py",
    "automated_api_call": False,
    "independence_warning": "The same assistant wrote eval/corpus.py gold labels; metrics computed from these files are NOT an independent measure of model accuracy.",
    "prompt_sha256": PROMPT_SHA256, "recorded_on": "2026-10-29", "artifacts": 15}, indent=2))
print("wrote", len(list(OUT.glob("A*.json"))), "recorded outputs")
