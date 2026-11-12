"""Mocked tests for the Groq extractor and provider selection. NO network is used and NO real key exists here.
They prove the request format (checked against Groq's API reference on 2026-11-12), the error handling and that the raw model text
goes through the SAME strict validator as every other extractor. They do NOT prove that the live Groq service behaves as documented;
that needs a real run (docs/GROQ.md)."""
import hashlib
import json
import os
import unittest
from unittest import mock

from tests.ext_helpers import *
from delivery_extraction import prompt as P
from delivery_extraction.llm import (GROQ_API_URL, GROQ_GPT_OSS_MODELS, GROQ_RETIRED_MODELS, AnthropicExtractor, GroqExtractor, LLMError,
                                     make_extractor)

KEY = "gsk_CANARY_DO_NOT_LEAK_0123456789"
RAW = (ROOT / "eval" / "recorded_outputs" / "A01.json").read_text()


def ok(text, finish="stop"):
    return 200, json.dumps({"choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}]}).encode()


def transport(reply, calls=None):
    def t(url, headers, body):
        if calls is not None:
            calls.append((url, dict(headers), body))
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, tuple) else ok(reply)
    return t


def groq(model="openai/gpt-oss-120b", reply=RAW, calls=None, **kw):
    return GroqExtractor(model=model, api_key=KEY, transport=transport(reply, calls), **kw)


class Configuration(unittest.TestCase):
    def test_model_is_required_and_never_guessed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMError) as cm:
                GroqExtractor(model=None, api_key="k", transport=transport(RAW))
        self.assertIn("no default is guessed", str(cm.exception))

    def test_missing_key_is_an_error_at_extract_time_and_names_the_variable(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            ex = GroqExtractor(model="openai/gpt-oss-20b", transport=transport(RAW))
        with self.assertRaises(LLMError) as cm:
            ex.extract(ART["A01"])
        self.assertIn("GROQ_API_KEY", str(cm.exception))

    def test_invalid_reasoning_effort_is_rejected(self):
        with self.assertRaises(LLMError):
            groq(reasoning_effort="extreme")

    def test_repr_never_contains_the_key(self):
        self.assertNotIn(KEY, repr(groq()))
        self.assertNotIn(KEY, str(groq()))


class RequestFormat(unittest.TestCase):
    def test_gpt_oss_request_matches_the_documented_chat_completions_format(self):
        calls = []
        out = groq(calls=calls).extract(ART["A01"])
        url, headers, body = calls[0]
        req = json.loads(body)
        self.assertEqual(url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer " + KEY)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertTrue(headers["User-Agent"].startswith("delivery-gate/"))
        self.assertEqual((req["model"], req["temperature"]), ("openai/gpt-oss-120b", 0))
        self.assertEqual(req["response_format"], {"type": "json_object"})
        self.assertEqual(req["messages"][0], {"role": "system", "content": P.SYSTEM_PROMPT})
        self.assertEqual(req["messages"][1]["role"], "user")
        self.assertIn("max_completion_tokens", req)
        self.assertNotIn("max_tokens", req, "max_tokens is deprecated in Groq's API; max_completion_tokens is used")
        self.assertEqual((req["reasoning_effort"], req["include_reasoning"]), ("low", False))
        self.assertEqual(out.request_sha256, hashlib.sha256(body).hexdigest())

    def test_json_mode_requires_the_word_json_in_the_prompt(self):
        self.assertIn("JSON", P.SYSTEM_PROMPT)

    def test_reasoning_parameters_are_sent_only_to_the_two_gpt_oss_models(self):
        for model in ("qwen/qwen3.8-27b", "some/other-model"):
            calls = []
            groq(model=model, calls=calls).extract(ART["A01"])
            req = json.loads(calls[0][2])
            self.assertNotIn("reasoning_effort", req, model)
            self.assertNotIn("include_reasoning", req, model)
        self.assertEqual(GROQ_GPT_OSS_MODELS, {"openai/gpt-oss-120b", "openai/gpt-oss-20b"})
        calls = []
        groq(model="openai/gpt-oss-20b", calls=calls, reasoning_effort="high").extract(ART["A01"])
        self.assertEqual(json.loads(calls[0][2])["reasoning_effort"], "high")

    def test_the_model_never_sees_policy(self):
        calls = []
        groq(reply="{}", calls=calls).extract(ART["A01"])
        body = calls[0][2].decode()
        for pid in REG.passages:
            self.assertNotIn(pid, body, pid)
        for banned in ("Seller Protection", "Transaction Details", "PARTIALLY_ELIGIBLE", "signature confirmation"):
            self.assertNotIn(banned, body, banned)

    def test_the_request_contains_no_credentials_in_its_body(self):
        calls = []
        groq(calls=calls).extract(ART["A01"])
        self.assertNotIn(KEY, calls[0][2].decode())


class ResponseHandling(unittest.TestCase):
    def test_provenance_fields_are_recorded_and_text_passes_the_same_strict_validator(self):
        out = groq().extract(ART["A01"])
        self.assertEqual((out.extractor_kind, out.model, out.prompt_sha256), ("GROQ_API", "openai/gpt-oss-120b", P.PROMPT_SHA256))
        self.assertEqual(len(validate_output(ART["A01"], out.text).accepted), 7)

    def test_garbage_from_the_model_is_rejected_by_the_validator_not_trusted(self):
        out = groq(reply='{"artifact_id": "A01", "facts": "PROTECTED"}').extract(ART["A01"])
        self.assertEqual(len(validate_output(ART["A01"], out.text).accepted), 0)

    def test_truncated_output_is_a_clear_error_not_a_partial_result(self):
        with self.assertRaises(LLMError) as cm:
            groq(reply=ok('{"artifact_id": "A01", "fac', finish="length")).extract(ART["A01"])
        self.assertIn("max_completion_tokens", str(cm.exception))

    def test_empty_or_missing_answer_text_is_an_error(self):
        for reply in (ok(""), ok("   "), (200, json.dumps({"choices": [{"message": {"role": "assistant", "content": None, "reasoning": "x"}, "finish_reason": "stop"}]}).encode())):
            with self.assertRaises(LLMError):
                groq(reply=reply).extract(ART["A01"])

    def test_unexpected_response_shapes_are_errors(self):
        for body in (b"not json", b"[]", b"{}", json.dumps({"choices": []}).encode(), json.dumps({"choices": [{}]}).encode()):
            with self.assertRaises(LLMError, msg=body):
                groq(reply=(200, body)).extract(ART["A01"])


class Errors(unittest.TestCase):
    def err(self, status, body=None):
        payload = json.dumps(body).encode() if body is not None else b""
        with self.assertRaises(LLMError) as cm:
            groq(model="llama-3.3-70b-versatile", reply=(status, payload)).extract(ART["A01"])
        return str(cm.exception)

    def test_status_codes_are_explained_and_never_swallowed(self):
        self.assertIn("check GROQ_API_KEY", self.err(401, {"error": {"message": "Invalid API Key", "type": "invalid_request_error", "code": "invalid_api_key"}}))
        self.assertIn("rate limited", self.err(429, {"error": {"message": "Rate limit reached", "type": "tokens", "code": "rate_limit_exceeded"}}))
        self.assertIn("HTTP 500", self.err(500))
        self.assertIn("invalid_api_key", self.err(401, {"error": {"code": "invalid_api_key"}}))

    def test_a_retired_model_gets_a_specific_replacement_hint(self):
        msg = self.err(404, {"error": {"message": "The model `llama-3.3-70b-versatile` does not exist", "code": "model_not_found"}})
        self.assertIn("openai/gpt-oss-120b", msg)
        self.assertIn("retired", msg)
        msg400 = self.err(400, {"error": {"message": "model_decommissioned", "code": "model_decommissioned"}})
        self.assertIn("openai/gpt-oss-120b", msg400)

    def test_current_models_get_no_retirement_hint(self):
        with self.assertRaises(LLMError) as cm:
            groq(model="openai/gpt-oss-120b", reply=(404, b"{}")).extract(ART["A01"])
        self.assertNotIn("retired", str(cm.exception))

    def test_retirement_table_matches_groqs_published_replacements(self):
        self.assertEqual(GROQ_RETIRED_MODELS["llama-3.1-8b-instant"], "openai/gpt-oss-20b")
        self.assertEqual(GROQ_RETIRED_MODELS["llama-3.3-70b-versatile"], "openai/gpt-oss-120b")
        self.assertEqual(GROQ_RETIRED_MODELS["qwen/qwen3.6-27b"], "qwen/qwen3.8-27b")
        self.assertFalse(set(GROQ_RETIRED_MODELS) & GROQ_GPT_OSS_MODELS, "a current model must never be listed as retired")

    def test_long_error_messages_are_truncated(self):
        msg = self.err(400, {"error": {"message": "x" * 5000}})
        self.assertLess(len(msg), 700)

    def test_network_failures_become_llm_errors_without_secrets(self):
        for exc in (TimeoutError("slow"), ConnectionResetError("reset"), OSError("dns")):
            with self.assertRaises(LLMError) as cm:
                groq(reply=exc).extract(ART["A01"])
            self.assertNotIn(KEY, str(cm.exception))
            self.assertIn("network error", str(cm.exception))

    def test_the_key_never_appears_in_any_error(self):
        for status in (400, 401, 403, 404, 429, 500, 503):
            with self.assertRaises(LLMError) as cm:
                groq(reply=(status, json.dumps({"error": {"message": "boom", "code": "c", "type": "t"}}).encode())).extract(ART["A01"])
            self.assertNotIn(KEY, str(cm.exception))


class ProviderSelection(unittest.TestCase):
    def test_nothing_configured_means_offline_fixtures_only(self):
        self.assertIsNone(make_extractor({}))
        self.assertIsNone(make_extractor({"EXTRACTION_MODEL": "m"}))
        self.assertIsNone(make_extractor({"GROQ_API_KEY": KEY}), "a key without a model is not configured; the model is never guessed")

    def test_groq_is_chosen_when_its_key_is_present(self):
        ex = make_extractor({"GROQ_API_KEY": KEY, "EXTRACTION_MODEL": "openai/gpt-oss-120b"})
        self.assertIsInstance(ex, GroqExtractor)
        self.assertEqual(ex.KIND, "GROQ_API")

    def test_groq_wins_when_both_keys_exist_and_no_provider_is_named(self):
        ex = make_extractor({"GROQ_API_KEY": KEY, "ANTHROPIC_API_KEY": "a", "EXTRACTION_MODEL": "m"})
        self.assertIsInstance(ex, GroqExtractor)

    def test_explicit_provider_is_honoured_exactly(self):
        env = {"GROQ_API_KEY": KEY, "ANTHROPIC_API_KEY": "a", "EXTRACTION_MODEL": "m", "EXTRACTION_PROVIDER": "anthropic"}
        self.assertIsInstance(make_extractor(env), AnthropicExtractor)
        env["EXTRACTION_PROVIDER"] = "GROQ"
        self.assertIsInstance(make_extractor(env), GroqExtractor)

    def test_explicit_provider_without_its_key_is_an_error_not_a_silent_fallback(self):
        with self.assertRaises(LLMError):
            make_extractor({"ANTHROPIC_API_KEY": "a", "EXTRACTION_MODEL": "m", "EXTRACTION_PROVIDER": "groq"})

    def test_unknown_provider_is_an_error(self):
        with self.assertRaises(LLMError):
            make_extractor({"GROQ_API_KEY": KEY, "EXTRACTION_MODEL": "m", "EXTRACTION_PROVIDER": "openai"})

    def test_existing_anthropic_only_configuration_still_works(self):
        ex = make_extractor({"ANTHROPIC_API_KEY": "a", "EXTRACTION_MODEL": "m"})
        self.assertIsInstance(ex, AnthropicExtractor)

    def test_reasoning_effort_can_be_set_from_the_environment_and_is_validated(self):
        ex = make_extractor({"GROQ_API_KEY": KEY, "EXTRACTION_MODEL": "openai/gpt-oss-20b", "EXTRACTION_REASONING_EFFORT": "Medium"})
        self.assertEqual(ex.reasoning_effort, "medium")
        with self.assertRaises(LLMError):
            make_extractor({"GROQ_API_KEY": KEY, "EXTRACTION_MODEL": "m", "EXTRACTION_REASONING_EFFORT": "max"})


class AppIntegration(unittest.TestCase):
    def test_recorded_samples_stay_offline_even_when_a_live_key_is_configured(self):
        from delivery_ui.service import default_extractor_factory
        from delivery_extraction.extractor import RecordedExtractor
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": KEY, "EXTRACTION_MODEL": "openai/gpt-oss-120b"}, clear=True):
            ex, kind, msg = default_extractor_factory(ART["A01"], "A01")
        self.assertEqual((kind, msg), (RecordedExtractor.KIND, None))

    def test_unrecognised_text_uses_groq_when_configured_else_says_why_not(self):
        from delivery_ui.service import default_extractor_factory
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": KEY, "EXTRACTION_MODEL": "openai/gpt-oss-120b"}, clear=True):
            ex, kind, msg = default_extractor_factory(ART["A01"], None)
        self.assertEqual((kind, msg), ("GROQ_API", None))
        self.assertIsInstance(ex, GroqExtractor)
        with mock.patch.dict(os.environ, {}, clear=True):
            ex, kind, msg = default_extractor_factory(ART["A01"], None)
        self.assertIsNone(ex)
        self.assertIn("No extraction model is configured", msg)
        with mock.patch.dict(os.environ, {"EXTRACTION_PROVIDER": "groq", "EXTRACTION_MODEL": "m"}, clear=True):
            ex, kind, msg = default_extractor_factory(ART["A01"], None)
        self.assertIsNone(ex)
        self.assertIn("API key variable is not set", msg)


class CheckCommand(unittest.TestCase):
    """python3 -m delivery_extraction.groq_check, with both network functions replaced by fakes."""
    ENV = {"GROQ_API_KEY": KEY, "EXTRACTION_MODEL": "openai/gpt-oss-120b"}

    def run_check(self, argv=(), env=None, models=("openai/gpt-oss-120b", "openai/gpt-oss-20b", "whisper-large-v3"), list_status=200,
                  extract_reply=RAW, extract_calls=None):
        import io
        from delivery_extraction import groq_check
        listed = []
        def get(key):
            listed.append(key)
            return list_status, json.dumps({"object": "list", "data": [{"id": m} for m in models]}).encode()
        out = io.StringIO()
        rc = groq_check.main(list(argv), env=self.ENV if env is None else env, list_transport=get, extract_transport=transport(extract_reply, extract_calls), out=out)
        return rc, out.getvalue(), listed

    def test_missing_configuration_makes_no_request(self):
        rc, text, listed = self.run_check(env={})
        self.assertEqual((rc, listed), (2, []))
        self.assertIn("GROQ_API_KEY", text)
        self.assertIn("EXTRACTION_MODEL", text)
        rc, text, listed = self.run_check(env={"GROQ_API_KEY": KEY})
        self.assertEqual((rc, listed), (2, []))

    def test_available_model_passes(self):
        rc, text, listed = self.run_check()
        self.assertEqual(rc, 0)
        self.assertEqual(listed, [KEY])
        self.assertIn("OK: EXTRACTION_MODEL 'openai/gpt-oss-120b' is available", text)

    def test_unavailable_retired_model_names_its_replacement(self):
        rc, text, _ = self.run_check(env={**self.ENV, "EXTRACTION_MODEL": "llama-3.3-70b-versatile"})
        self.assertEqual(rc, 4)
        self.assertIn("MODEL NOT AVAILABLE", text)
        self.assertIn("openai/gpt-oss-120b", text)
        self.assertIn("retired", text)

    def test_unknown_model_is_reported_without_inventing_a_replacement_claim(self):
        rc, text, _ = self.run_check(env={**self.ENV, "EXTRACTION_MODEL": "made/up-model"})
        self.assertEqual(rc, 4)
        self.assertNotIn("retired", text)

    def test_list_failure_exits_3_and_never_prints_the_key(self):
        rc, text, _ = self.run_check(list_status=401)
        self.assertEqual(rc, 3)
        self.assertIn("check GROQ_API_KEY", text)
        self.assertNotIn(KEY, text)

    def test_extract_runs_one_extraction_through_the_strict_validator(self):
        calls = []
        rc, text, _ = self.run_check(["--extract"], extract_calls=calls)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("accepted 7 fact(s)", text)
        self.assertIn("GROQ_API", text)
        self.assertNotIn(KEY, text)

    def test_extract_with_unusable_model_output_exits_5(self):
        rc, text, _ = self.run_check(["--extract"], extract_reply='{"artifact_id": "A01", "facts": "PROTECTED"}')
        self.assertEqual(rc, 5)
        self.assertIn("NO FACTS ACCEPTED", text)

    def test_extract_request_failure_exits_3(self):
        rc, text, _ = self.run_check(["--extract"], extract_reply=(429, b"{}"))
        self.assertEqual(rc, 3)
        self.assertIn("rate limited", text)
        self.assertNotIn(KEY, text)

    def test_without_the_extract_flag_no_extraction_request_is_made(self):
        calls = []
        self.run_check(extract_calls=calls)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
