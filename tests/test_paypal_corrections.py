import ast, copy, hashlib, json, unittest
from pathlib import Path
from delivery_gate.engine import assess
from delivery_gate.models import Case, ClaimCategory, ProtectionAssessment, ProvStatus, SourceType
from paypal_adapter import adapter, api_semantics as sem, disputes, exposure, sources, webhooks
from paypal_adapter.handoff import ALLOWED_FACTS, merchant_jurisdiction_fact, to_case
from tests.paypal_helpers import *

DFIX = FIXTURES / "disputes"
CAP_ID = "FXCAP0000000001"


def dresp(name):
    return copy.deepcopy(json.loads((DFIX / f"{name}.json").read_text())["response"])


def dobs(name, **kw):
    return disputes.observe_dispute(dresp(name), origin="FIXTURE", **kw)


def cap01():
    return observe(response("01_normal")).select_capture()


def dispute_with(reason=None, channel=None, stage=None, **drop):
    r = dresp("d01_inr_internal_partial")
    for k, v in (("reason", reason), ("dispute_channel", channel), ("dispute_life_cycle_stage", stage)):
        if v is None:
            r.pop(k, None)
        else:
            r[k] = v
    return disputes.observe_dispute(r, origin="FIXTURE")


def engine_case(h, extra_category=None):
    names = {f.name for f in h.case.transaction_facts}
    extra = [merchant_fact("physical_goods", True), merchant_fact("pre_order_or_made_to_order", False), merchant_fact("transaction_details_address", S.TD_ADDR)]
    if "merchant_account_country" not in names:
        extra.append(merchant_jurisdiction_fact("US", source_ref="fixture:merchant-config"))
    cat = h.case.fact("claim_category")
    ev = CATEGORIES[cat.value]() if cat is not None else ()
    return Case(h.case.case_id, h.case.transaction_facts + tuple(extra), tuple(ev))


class ApiSemanticsLayer(unittest.TestCase):
    def test_per_token_meanings_are_recorded_with_exact_source_references(self):
        e, p, n = (sem.lookup(sem.SPS, t) for t in ("ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"))
        self.assertEqual(len(e.described_claim_types), 2)                                
        self.assertEqual(len(p.described_claim_types), 1)                                  
        self.assertEqual(n.described_claim_types, ())
        for row in (e, p, n):
            self.assertEqual(row.meaning_status, "DOCUMENTED")
            self.assertEqual(row.sources, ("https://developer.paypal.com/api/orders/v2/definitions/capture#seller_protection.status",))
            self.assertEqual(row.retrieved, "2026-11-01")
        self.assertIn("did not receive", p.described_claim_types[0])

    def test_no_row_asserts_legal_policy_equivalence(self):
        for row in sem.all_rows():
            self.assertEqual(row.legal_policy_equivalence, "NOT_ESTABLISHED", row.semantics_id)
        for t in ("ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"):
            self.assertIn("Transaction Details", sem.lookup(sem.SPS, t).equivalence_note)

    def test_api_vocabulary_is_not_delivery_gate_vocabulary(self):
        cats = {c.value for c in ClaimCategory}
        for row in sem.all_rows():
            self.assertFalse(cats & set(row.described_claim_types), row.semantics_id)

    def test_values_without_a_retrieved_description_are_marked_name_only(self):
        r = sem.lookup(sem.RS, "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED")
        self.assertEqual((r.meaning_status, r.documented_meaning), ("NAME_ONLY", None))
        self.assertEqual(sem.lookup(sem.LS, "CHARGEBACK").meaning_status, "NAME_ONLY")
        self.assertIsNone(sem.lookup(sem.SPS, "ELIGIBLE_V2"))

    def test_cross_surface_difference_is_recorded_not_resolved(self):
        self.assertTrue(any("Partially Eligible Unauth Only" in n["says"] for n in sem.CROSS_SURFACE_NOTES))

    def test_observations_point_at_the_semantics_row_and_the_engine_never_sees_it(self):
        c = cap01()
        self.assertEqual(c.find("seller_protection.status").api_semantics_ref, "orders_v2.capture.seller_protection.status=ELIGIBLE")
        self.assertIsNone(observe(response("10_unexpected_enum")).select_capture().find("seller_protection.status").api_semantics_ref)
        h = to_case(c)
        self.assertEqual(h.case.fact("paypal_seller_protection_status").value, "ELIGIBLE")        
        self.assertNotIn("api_semantics", json.dumps(h.case.snapshot()))

    def test_documented_api_meaning_does_not_change_the_policy_assessment(self):
        by = {t: policy_view(assessment(with_status(response("01_normal"), t), "UNAUTHORIZED_TRANSACTION"), t) for t in ("ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE")}
        self.assertEqual(by["ELIGIBLE"], by["PARTIALLY_ELIGIBLE"])
        self.assertEqual(by["ELIGIBLE"], by["NOT_ELIGIBLE"])


class ExposureSeparation(unittest.TestCase):
    def test_three_quantities_are_kept_apart(self):
        x = exposure.build_exposure(cap01(), dobs("d01_inr_internal_partial")).to_dict()
        self.assertEqual((x["original_transaction_value"]["state"], x["original_transaction_value"]["value"]), ("OBSERVED", "1200.00"))
        self.assertEqual((x["disputed_amount"]["state"], x["disputed_amount"]["value"]), ("OBSERVED", "300.00"))
        self.assertEqual(x["potential_seller_exposure"]["state"], "UNKNOWN")
        self.assertEqual(x["potential_seller_exposure"]["reason"], "NO_REVIEWED_POLICY_RULE_DEFINES_POTENTIAL_SELLER_EXPOSURE")

    def test_disputed_amount_is_unknown_without_a_dispute(self):
        x = exposure.build_exposure(cap01()).to_dict()
        self.assertEqual((x["disputed_amount"]["state"], x["disputed_amount"]["value"], x["disputed_amount"]["reason"]), ("UNKNOWN", None, "NO_DISPUTE_OBSERVED"))
        self.assertEqual(x["original_transaction_value"]["value"], "1200.00")

    def test_potential_exposure_is_never_derived(self):
        for d in (None, dobs("d01_inr_internal_partial"), dobs("d02_unauthorised_internal")):
            x = exposure.build_exposure(cap01(), d)
            self.assertEqual((x.potential_seller_exposure["state"], x.potential_seller_exposure["value"]), ("UNKNOWN", None))

    def test_unlinked_unusable_or_inconsistent_disputes_yield_unknown_not_a_guess(self):
        cases = {"d11_other_transaction": "DISPUTE_NOT_LINKED_TO_CAPTURE", "d08_missing_amount_and_channel": "DISPUTE_AMOUNT_NOT_OBSERVED_OR_UNUSABLE",
                 "d12_currency_differs": "CURRENCY_MISMATCH_OR_UNKNOWN"}
        for n, reason in cases.items():
            x = exposure.build_exposure(cap01(), dobs(n))
            self.assertEqual((x.disputed_amount["state"], x.disputed_amount["value"], x.disputed_amount["reason"]), ("UNKNOWN", None, reason), n)
        self.assertIn("CURRENCY_MISMATCH_OR_UNKNOWN", exposure.build_exposure(cap01(), dobs("d12_currency_differs")).flags)
        self.assertFalse(exposure.build_exposure(cap01(), dobs("d11_other_transaction")).linkage["linked"])

    def test_a_disputed_amount_above_the_capture_is_flagged_not_corrected(self):
        x = exposure.build_exposure(cap01(), dobs("d13_exceeds_capture"))
        self.assertEqual(x.disputed_amount["value"], "1500.00")
        self.assertIn("DISPUTED_AMOUNT_EXCEEDS_CAPTURE_AMOUNT", x.flags)

    def test_a_capture_without_a_usable_amount_has_an_unknown_original_value(self):
        r = response("01_normal"); del r["purchase_units"][0]["payments"]["captures"][0]["amount"]
        x = exposure.build_exposure(observe(r).select_capture(), dobs("d01_inr_internal_partial"))
        self.assertEqual(x.original_transaction_value["state"], "UNKNOWN")

    def test_the_capture_amount_is_never_called_a_floor_or_minimum(self):
        for d in (None, dobs("d01_inr_internal_partial")):
            text = json.dumps(exposure.build_exposure(cap01(), d).to_dict()).lower()
            for word in ("floor", "minimum", "lower_bound", "lower bound"):
                self.assertNotIn(word, text)
        for f in ("exposure.py", "disputes.py", "api_semantics.py", "sources.py"):
            src = (ROOT / "paypal_adapter" / f).read_text().lower()
            self.assertNotIn("exposure_floor", src, f)

    def test_inventory_and_handoff_do_not_present_the_amount_as_a_bound(self):
        row = next(f for f in inventory_rows() if f["path"] == "capture.amount.value")
        self.assertEqual(row["handoff"], "WITHHELD")
        self.assertIn("not a minimum disputed exposure", row["note"])


def inventory_rows():
    from paypal_adapter import inventory
    return inventory.inventory_rows()


class DisputesObservation(unittest.TestCase):
    def test_raw_reason_is_preserved_and_normalisation_is_documented(self):
        o = dobs("d01_inr_internal_partial").find("reason")
        self.assertEqual((o.raw_value, o.normalized_value, o.normalization), ("MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "ITEM_NOT_RECEIVED", "CLAIM_REASON_TABLE_V1:ESTABLISHED"))
        o = dobs("d02_unauthorised_internal").find("reason")
        self.assertEqual((o.raw_value, o.normalized_value), ("UNAUTHORISED", "UNAUTHORIZED_TRANSACTION"))
        t = disputes.normalization_tables()["claim_reason_table_v1"]
        self.assertTrue(t["UNAUTHORISED"]["established"] and t["UNAUTHORISED"]["basis"])
        self.assertFalse(t["MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"]["established"])

    def test_unestablished_or_out_of_scope_reasons_are_not_normalised(self):
        for n in ("d06_not_as_described", "d07_other_reason", "d09_unexpected_enums"):
            o = dobs(n).find("reason")
            self.assertIsNone(o.normalized_value, n)
            self.assertIsNotNone(o.raw_value, n)
        self.assertEqual(dobs("d06_not_as_described").find("reason").normalization, "CLAIM_REASON_TABLE_V1:NOT_ESTABLISHED")
        h = to_case(cap01(), dispute=dobs("d06_not_as_described"))
        self.assertIsNone(h.case.fact("claim_category"))
        self.assertTrue(any("not normalised" in c for c in h.cautions))

    def test_lifecycle_stage_is_its_own_observation(self):
        d = dobs("d03_inr_external_chargeback")
        self.assertEqual(d.find("dispute_life_cycle_stage").raw_value, "CHARGEBACK")
        self.assertEqual(d.find("reason").raw_value, "MERCHANDISE_OR_SERVICE_NOT_RECEIVED")        
        self.assertEqual(d.find("dispute_life_cycle_stage").api_semantics_ref, "disputes_v1.dispute.dispute_life_cycle_stage=CHARGEBACK")
        self.assertIsNone(sem.lookup(sem.LS, "CHARGEBACK").documented_meaning)                     
        from paypal_adapter.handoff import DISPUTE_HANDOFF_PLAN
        self.assertNotIn("dispute_life_cycle_stage", {local for _, local in DISPUTE_HANDOFF_PLAN}) 

    def test_route_comes_from_the_channel_alone(self):
        for n, route in (("d01_inr_internal_partial", "PAYPAL_DISPUTE"), ("d03_inr_external_chargeback", None), ("d04_unauthorised_external", None),
                         ("d05_alert_channel", None), ("d08_missing_amount_and_channel", None), ("d09_unexpected_enums", None)):
            d = dobs(n)
            ch = d.find("dispute_channel")
            self.assertEqual(ch.normalized_value if ch is not None else None, route, n)
            f = to_case(cap01(), dispute=d).case.fact("route")
            self.assertEqual(f.value if f is not None else None, route, n)

    def test_route_is_never_inferred_from_the_claim_reason_or_stage(self):
        for reason in disputes.DOCUMENTED_REASONS:
            for stage in ("INQUIRY", "CHARGEBACK", "PRE_ARBITRATION", "ARBITRATION", None):
                h = to_case(cap01(), dispute=dispute_with(reason, None, stage))
                self.assertIsNone(h.case.fact("route"), (reason, stage))             
            for ch, want in (("INTERNAL", "PAYPAL_DISPUTE"), ("EXTERNAL", None), ("ALERT", None)):
                f = to_case(cap01(), dispute=dispute_with(reason, ch, "INQUIRY")).case.fact("route")
                self.assertEqual(f.value if f else None, want, (reason, ch))

    def test_claim_category_does_not_depend_on_channel_or_stage(self):
        for ch in ("INTERNAL", "EXTERNAL", "ALERT", None):
            for st in ("INQUIRY", "CHARGEBACK", None):
                f = to_case(cap01(), dispute=dispute_with("UNAUTHORISED", ch, st)).case.fact("claim_category")
                self.assertEqual(f.value, "UNAUTHORIZED_TRANSACTION", (ch, st))

    def test_external_disputes_are_not_mapped_because_they_include_ach_returns(self):
        n = disputes.normalization_tables()["channel_route_table_v1"]["EXTERNAL"]
        self.assertFalse(n["established"])
        self.assertIn("ACH", n["note"])
        self.assertIn("ACH returns", sem.lookup(sem.CH, "EXTERNAL").documented_meaning)

    def test_undocumented_tokens_are_preserved_and_flagged(self):
        d = dobs("d09_unexpected_enums")
        for k, v in (("reason", "NEW_REASON"), ("dispute_channel", "NEW_CHANNEL"), ("dispute_life_cycle_stage", "NEW_STAGE"), ("status", "NEW_STATUS")):
            self.assertEqual((d.find(k).raw_value, d.find(k).enum_state), (v, "UNDOCUMENTED_TOKEN"))
        self.assertEqual(len([a for a in d.anomalies if a.kind == "UNDOCUMENTED_ENUM_VALUE"]), 4)

    def test_missing_fields_are_absent_not_defaulted_and_malformed_fails_safely(self):
        d = dobs("d08_missing_amount_and_channel")
        self.assertIsNone(d.find("dispute_amount.value"))
        self.assertTrue({"dispute_amount", "dispute_channel"} <= {a.local_path for a in d.absent})
        for bad in (None, [], {"reason": "OTHER"}, {"dispute_id": 7}, dresp("d10_malformed")):
            with self.assertRaises(adapter.MalformedPayPalResponse):
                disputes.observe_dispute(bad, origin="FIXTURE")

    def test_provenance_and_determinism(self):
        for n in sorted(p.stem for p in DFIX.glob("*.json") if p.stem != "d10_malformed"):
            r = dresp(n); sha = adapter.sha256_hex(adapter.canonical(r))
            d = disputes.observe_dispute(r, origin="FIXTURE")
            self.assertEqual(d.to_dict(), disputes.observe_dispute(copy.deepcopy(r), origin="FIXTURE").to_dict(), n)
            for o in d.observations:
                self.assertEqual((o.source, o.origin, o.api, o.response_sha256), ("PAYPAL_API", "FIXTURE", "PayPal Disputes v1", sha), n)
                self.assertTrue(o.doc_ref.startswith("https://") and o.field_path and o.observation_id.startswith("fixture:paypal-dispute:"), n)
                self.assertIsNone(o.observed_at, n)


class HandoffWithDispute(unittest.TestCase):
    def test_linked_dispute_facts_are_handed_over_with_paypal_provenance(self):
        h = to_case(cap01(), dispute=dobs("d01_inr_internal_partial"))
        self.assertEqual(h.case.fact("claim_category").value, "ITEM_NOT_RECEIVED")
        self.assertEqual(h.case.fact("route").value, "PAYPAL_DISPUTE")
        for n in ("claim_category", "route"):
            p = h.case.fact(n).provenance
            self.assertEqual((p.source_type, p.status), (SourceType.PAYPAL_API, ProvStatus.SYSTEM_RECORD))
            self.assertTrue(p.source_ref.startswith("fixture:paypal-dispute:"))
        self.assertTrue(h.linkage["linked"])
        self.assertIsNone(h.case.fact("transaction_amount"))                           
        self.assertFalse({f.name for f in h.case.transaction_facts} - ALLOWED_FACTS)

    def test_an_unlinked_dispute_contributes_nothing(self):
        h = to_case(cap01(), dispute=dobs("d11_other_transaction"))
        self.assertIsNone(h.case.fact("claim_category"))
        self.assertIsNone(h.case.fact("route"))
        self.assertFalse(h.linkage["linked"])
        self.assertTrue(any(w["reason"] == "DISPUTE_NOT_LINKED_TO_CAPTURE" for w in h.withheld))

    def test_engine_end_to_end_with_each_documented_route_outcome(self):
        a = assess(REG, engine_case(to_case(cap01(), dispute=dobs("d01_inr_internal_partial"))))
        self.assertEqual(a.protection_assessment, ProtectionAssessment.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        ext = assess(REG, engine_case(to_case(cap01(), dispute=dobs("d03_inr_external_chargeback"))))
        self.assertEqual(ext.protection_assessment, ProtectionAssessment.UNKNOWN)        
        self.assertTrue(ext.observed_inputs["route"]["state"] != "SUPPLIED")
        self.assertEqual((ext.policy_status, ext.paypal_acceptance), ("UNREVIEWED", "NOT_ESTABLISHED"))

    def test_merchant_jurisdiction_is_asserted_or_unknown_never_paypal_verified(self):
        self.assertIsNone(merchant_jurisdiction_fact(None, source_ref="x"))
        self.assertIsNone(merchant_jurisdiction_fact("  ", source_ref="x"))
        f = merchant_jurisdiction_fact("US", source_ref="fixture:merchant-config")
        self.assertEqual((f.provenance.source_type, f.provenance.status), (SourceType.MERCHANT_INPUT, ProvStatus.MERCHANT_ASSERTED))
        self.assertFalse(any(f.name == "merchant_account_country" for f in to_case(cap01()).case.transaction_facts))   


class Webhooks(unittest.TestCase):
    HEADERS = {h: "x" for h in webhooks.REQUIRED_HEADERS}

    class Ok:
        def verify(self, headers, event, webhook_id):
            return "SUCCESS"

    class Boom:
        def verify(self, headers, event, webhook_id):
            raise RuntimeError("network")

    class Bad:
        def verify(self, headers, event, webhook_id):
            return "FAILURE"

    @staticmethod
    def event(eid="WH-1", etype="CUSTOMER.DISPUTE.CREATED", **res):
        return {"id": eid, "event_type": etype, "resource": {"dispute_id": "PP-D-FX0001", "dispute_amount": {"value": "300.00"}, "reason": "UNAUTHORISED",
                                                              "dispute_channel": "EXTERNAL", **res}}

    def test_unverified_notifications_trigger_nothing(self):
        for v in (webhooks.UnconfiguredVerifier(), self.Bad(), self.Boom()):
            d = webhooks.WebhookReceiver(v, "WHID").receive(self.HEADERS, self.event())
            self.assertEqual((d.accepted, d.reason, d.read_request), (False, "SIGNATURE_NOT_VERIFIED", None))
        for missing in webhooks.REQUIRED_HEADERS:
            h = {k: v for k, v in self.HEADERS.items() if k != missing}
            self.assertEqual(webhooks.WebhookReceiver(self.Ok(), "W").receive(h, self.event()).reason, f"MISSING_HEADER:{missing}")

    def test_a_verified_notification_yields_only_a_fresh_read_request(self):
        d = webhooks.WebhookReceiver(self.Ok(), "W").receive({k.lower(): v for k, v in self.HEADERS.items()}, self.event())
        self.assertTrue(d.accepted)
        self.assertEqual(vars(d.read_request), {"dispute_id": "PP-D-FX0001", "event_id": "WH-1", "event_type": "CUSTOMER.DISPUTE.CREATED", "purpose": "FRESH_DISPUTES_API_READ"})
        self.assertNotIn("300.00", json.dumps(vars(d.read_request)))                   

    def test_other_events_malformed_events_and_duplicates_are_rejected(self):
        r = webhooks.WebhookReceiver(self.Ok(), "W")
        self.assertEqual(r.receive(self.HEADERS, self.event(etype="PAYMENT.CAPTURE.COMPLETED")).reason, "EVENT_TYPE_NOT_HANDLED")
        self.assertEqual(r.receive(self.HEADERS, "x").reason, "MALFORMED_EVENT")
        self.assertEqual(r.receive(self.HEADERS, {"event_type": "CUSTOMER.DISPUTE.CREATED"}).reason, "MALFORMED_EVENT")
        e = self.event(); e["resource"].pop("dispute_id")
        self.assertEqual(r.receive(self.HEADERS, e).reason, "NO_DISPUTE_ID")
        self.assertTrue(r.receive(self.HEADERS, self.event("WH-9")).accepted)
        self.assertEqual(r.receive(self.HEADERS, self.event("WH-9")).reason, "DUPLICATE_EVENT")
        with self.assertRaises(ValueError):
            webhooks.WebhookReceiver(self.Ok(), "")

    def test_no_facts_can_flow_from_a_webhook(self):
        for p in (ROOT / "paypal_adapter").glob("*.py"):
            if p.name != "webhooks.py":
                self.assertNotIn("webhooks", Architecture.imports(p), p.name)                 # nothing that builds observations or facts can see it
        self.assertFalse({"delivery_gate"} & Architecture.imports(ROOT / "paypal_adapter" / "webhooks.py"))


class Architecture(unittest.TestCase):
    @staticmethod
    def imports(path):
        out = set()
        for node in ast.walk(ast.parse(Path(path).read_text())):
            if isinstance(node, ast.ImportFrom):
                out |= {node.module.split(".")[0]} if node.module else set()
                out |= {a.name for a in node.names} if node.level else set()
            elif isinstance(node, ast.Import):
                out |= {a.name.split(".")[0] for a in node.names}
        return out

    def test_observation_modules_still_do_not_import_the_engine(self):
        for f in ("adapter.py", "inventory.py", "api_semantics.py", "disputes.py", "exposure.py", "webhooks.py", "sources.py"):
            self.assertNotIn("delivery_gate", self.imports(ROOT / "paypal_adapter" / f), f)

    def test_source_roles_match_the_reviewed_architecture(self):
        r = {x["input_name"]: x for x in sources.source_roles()}
        self.assertEqual(r["Dispute Detail Custom report"]["role"], "SUPPLEMENTARY")
        self.assertFalse(r["Dispute Detail Custom report"]["mandatory"])
        self.assertEqual(r["webhook notification"]["role"], "TRIGGER_ONLY")
        self.assertEqual(r["merchant_account_country"]["role"], "ASSERTED")
        self.assertIn("dispute_channel", r["dispute_route"]["source"])
        self.assertEqual(r["lifecycle_stage"]["source"].count("separate field"), 1)
        self.assertEqual(r["transaction_details_address"]["role"], "UNKNOWN")
        self.assertEqual(r["claim_category / reason"]["source"].split(":")[0], "Disputes API")
        self.assertFalse([x for x in r.values() if x["mandatory"] and x["input_name"] != "original_transaction_value"])


class Phase1EngineUntouched(unittest.TestCase):
    def test_engine_registry_policy_and_schemas_match_the_approved_hashes(self):
        rec = json.loads((ROOT / "tests" / "phase1_engine_hashes.json").read_text())["files"]
        self.assertEqual(len(rec), 10)
        for rel, want in rec.items():
            p = ROOT / rel
            self.assertTrue(p.is_file(), rel)
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), want, f"{rel} changed: this needs a separately reviewed policy change")
        live = {str(p.relative_to(ROOT)) for d in ("policy", "schemas") for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in str(p)}
        self.assertEqual({k for k in rec if k.startswith(("policy", "schemas"))}, live)       


if __name__ == "__main__":
    unittest.main()
