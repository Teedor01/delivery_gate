"""Phase 3 architectural refinement: content ATTRIBUTION (who a statement is attributed to) is kept apart from source AUTHENTICITY
(is the artifact genuine). `attribution = CARRIER_STATEMENT` never implies an authentic artifact."""
import unittest
from unittest import mock
from dataclasses import replace
from delivery_extraction import bridge
from delivery_extraction.review import Attestation, ReviewAction, ReviewDecision, ReviewError
from delivery_gate.models import Provenance, ProvStatus, SourceAuthenticity as SA, SourceType as ST, EvidenceFact
from tests.ext_helpers import *

CARRIER = ReviewAction.APPROVE_AS_CARRIER_DOCUMENT
MERCH = ReviewAction.APPROVE_AS_MERCHANT_ASSERTION
ORIG_PROVENANCE = bridge._provenance
ORIG_ATT_INIT = Attestation.__post_init__
ORIG_PROV_INIT = Provenance.__post_init__


def approve(aid, ids, action=CARRIER):
    return [ReviewDecision(f"{aid}#{i}", action, "reviewer-1") for i in ids]


def auth_violations():
    v = []

    def check(name, fn):
        try:
            msg = fn()
        except Exception as e:
            v.append(f"{name}: raised {type(e).__name__}: {e}")
            return
        if msg:
            v.append(f"{name}: {msg}")

    def model_guards():
        for kw in (dict(source_type=ST.CARRIER_DOCUMENT, status=ProvStatus.HUMAN_CONFIRMED, source_authenticity="VERIFIED"),
                   dict(source_type=ST.MERCHANT_STATEMENT, status=ProvStatus.HUMAN_CONFIRMED, source_authenticity="VERIFIED"),
                   dict(source_type=ST.CARRIER_DOCUMENT, status=ProvStatus.EXTRACTED_UNREVIEWED, source_authenticity="REVIEWED")):
            try:
                Provenance(source_ref="x", **kw)
            except ValueError:
                continue
            return f"model accepted {kw}"

    def reviewer_cannot_verify():
        for a in ("VERIFIED", "UNVERIFIED", "ANYTHING"):
            try:
                Attestation("A01", "r", authenticity=a)
            except ReviewError:
                continue
            return f"an attestation was created with authenticity {a!r}"

    def attribution_alone_is_not_authenticity():
        br = build_case(base_case(), facts_of("A01"), ART)                              # carrier-attributed facts, nobody reviewed anything
        if not br.bridged:
            return "expected unreviewed facts to be bridged"
        for b in br.bridged:
            if (b["source_type"], b["source_authenticity"], b["provenance_status"]) != ("EXTRACTED_FROM_TEXT", "UNVERIFIED", "EXTRACTED_UNREVIEWED"):
                return f"{b['fact_id']} became {b['source_type']}/{b['source_authenticity']} without an attestation"

    def carrier_approval_needs_attestation():
        try:
            build_case(base_case(), facts_of("A01"), ART, approve("A01", ["f1"]))
        except ReviewError:
            return None
        return "carrier approval succeeded without an attestation"

    def attestation_confers_reviewed_only():
        br = build_case(base_case(), facts_of("A01"), ART, approve("A01", ["f1", "f3", "f4", "f6"]), [Attestation("A01", "r")])
        carrier_rows = [b for b in br.bridged if b["source_type"] == "CARRIER_DOCUMENT"]
        if not carrier_rows:
            return "no carrier-document rows were produced"
        for b in br.bridged:
            if b["source_authenticity"] == "VERIFIED":
                return f"{b['fact_id']} was VERIFIED by a reviewer path"
        if any(b["source_authenticity"] != "REVIEWED" for b in carrier_rows):
            return "a carrier-document row is not REVIEWED"

    def content_approval_is_not_authenticity():
        br = build_case(base_case(), facts_of("A01"), ART, approve("A01", ["f1", "f3"], MERCH), [Attestation("A01", "r")])
        for b in br.bridged:
            if b["fact_id"] in ("A01#f1", "A01#f3") and (b["source_type"], b["source_authenticity"]) != ("MERCHANT_STATEMENT", "UNVERIFIED"):
                return f"agreeing with the text as a merchant assertion produced {b['source_type']}/{b['source_authenticity']}"

    for n, f in (("model_guards", model_guards), ("reviewer_cannot_verify", reviewer_cannot_verify),
                 ("attribution_alone_is_not_authenticity", attribution_alone_is_not_authenticity),
                 ("carrier_approval_needs_attestation", carrier_approval_needs_attestation),
                 ("attestation_confers_reviewed_only", attestation_confers_reviewed_only),
                 ("content_approval_is_not_authenticity", content_approval_is_not_authenticity)):
        check(n, f)
    return v


def _m_attribution_grants_review(f, decision, artifact, attested):         # a carrier-attributed fact is treated as an authentic carrier document
    if decision is None and f.attribution == "CARRIER_STATEMENT":
        return Provenance(ST.CARRIER_DOCUMENT, f.fact_id, ProvStatus.HUMAN_CONFIRMED, None, None, f.source_span, SA.REVIEWED)
    return ORIG_PROVENANCE(f, decision, artifact, attested)


def _m_no_attestation_needed(f, decision, artifact, attested):             # the attestation requirement is skipped
    if decision is not None and decision.action == ReviewAction.APPROVE_AS_CARRIER_DOCUMENT:
        return Provenance(ST.CARRIER_DOCUMENT, f.fact_id, ProvStatus.HUMAN_CONFIRMED, None, None, f.source_span, SA.REVIEWED)
    return ORIG_PROVENANCE(f, decision, artifact, attested)


def _m_merchant_approval_reviewed(f, decision, artifact, attested):        # agreeing with the text is treated as authenticating the artifact
    if decision is not None and decision.action == ReviewAction.APPROVE_AS_MERCHANT_ASSERTION:
        return Provenance(ST.MERCHANT_STATEMENT, f.fact_id, ProvStatus.HUMAN_CONFIRMED, None, None, f.source_span, SA.REVIEWED)
    return ORIG_PROVENANCE(f, decision, artifact, attested)


def _m_reviewer_verifies(f, decision, artifact, attested):                 # the reviewer path hands out VERIFIED
    p = ORIG_PROVENANCE(f, decision, artifact, attested)
    return Provenance(ST.CARRIER_API, p.source_ref, ProvStatus.SYSTEM_RECORD, None, None, None, SA.VERIFIED) if p.source_type == ST.CARRIER_DOCUMENT else p


class Refinement(unittest.TestCase):
    def test_battery_passes_on_the_real_code(self):
        self.assertEqual(auth_violations(), [])

    def test_unset_authenticity_leaves_phase1_and_phase2_output_bit_identical(self):
        p = Provenance(ST.PAYPAL_API, "x", ProvStatus.SYSTEM_RECORD)
        self.assertNotIn("source_authenticity", p.to_dict())
        self.assertIn("source_authenticity", Provenance(ST.CARRIER_DOCUMENT, "x", ProvStatus.HUMAN_CONFIRMED, source_authenticity=SA.REVIEWED).to_dict())

    def test_verified_is_a_separate_provenance_source_not_an_upgrade_of_the_reviewed_document(self):
        api = Provenance(ST.CARRIER_API, "carrier-api:1Z999", ProvStatus.SYSTEM_RECORD, source_authenticity=SA.VERIFIED)
        self.assertEqual((api.source_type, api.source_authenticity), (ST.CARRIER_API, SA.VERIFIED))
        e = EvidenceFact("delivery_record", True, api)                                   # representable and accepted by the engine's model
        self.assertEqual(e.provenance.source_authenticity, SA.VERIFIED)
        with self.assertRaises(ValueError):                                              # the document path can never be VERIFIED
            Provenance(ST.CARRIER_DOCUMENT, "x", ProvStatus.HUMAN_CONFIRMED, source_authenticity=SA.VERIFIED)

    def test_the_bridge_never_produces_verified_from_any_review_path(self):
        produced = 0
        for aid in ("A01", "A08", "A09"):
            facts = facts_of(aid)
            ids = [f.fact_id.split("#")[1] for f in facts]
            for action in (CARRIER, MERCH):
                try:
                    br = build_case(base_case(), facts, ART, approve(aid, ids, action), [Attestation(aid, "r")])
                except ReviewError:
                    continue                                                              # promotion refused: nothing produced
                produced += len(br.bridged)
                self.assertTrue(all(b["source_authenticity"] != "VERIFIED" for b in br.bridged), (aid, action))
                self.assertTrue(all(b["source_authenticity"] in ("UNVERIFIED", "REVIEWED") for b in br.bridged), (aid, action))
        self.assertGreater(produced, 0)

    def test_attestation_is_per_artifact(self):
        with self.assertRaises(ReviewError):
            build_case(base_case(), facts_of("A01"), ART, approve("A01", ["f1"]), [Attestation("A08", "r")])

    def test_engine_treats_a_reviewed_carrier_document_exactly_as_before(self):
        br, a = assess_extraction(REG, base_case(), facts_of("A01"), ART, approve("A01", ["f1", "f3", "f4", "f6"]), [Attestation("A01", "r")])
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)

    def test_mutations_of_the_refinement_are_caught(self):
        cases = {
            "R1 carrier attribution alone grants REVIEWED": lambda: mock.patch.object(bridge, "_provenance", _m_attribution_grants_review),
            "R2 attestation requirement skipped": lambda: mock.patch.object(bridge, "_provenance", _m_no_attestation_needed),
            "R3 merchant-assertion approval marked REVIEWED": lambda: mock.patch.object(bridge, "_provenance", _m_merchant_approval_reviewed),
            "R4 reviewer path hands out VERIFIED": lambda: mock.patch.object(bridge, "_provenance", _m_reviewer_verifies),
            "R5 attestation may carry VERIFIED": lambda: mock.patch.object(Attestation, "__post_init__", lambda self: None),
            "R6 provenance model stops guarding authenticity": lambda: mock.patch.object(Provenance, "__post_init__", lambda self: None),
        }
        for label, ctx in cases.items():
            with ctx():
                self.assertTrue(auth_violations(), label)


if __name__ == "__main__":
    unittest.main()
