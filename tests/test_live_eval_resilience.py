"""Rate-limit handling, checkpoint/resume and CLI behaviour of the live evaluation. Every network call is mocked: no Groq credit is used."""
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from delivery_extraction.extractor import RawExtraction
from delivery_extraction.llm import GroqExtractor, LLMError, LLMRetryExhausted, RetryPolicy, parse_retry_after
from eval import evaluate as EV
from eval.live_cache import LiveCache, cache_meta, schema_fingerprint
from tests.ext_helpers import ART, ROOT

RAW = (ROOT / "eval" / "recorded_outputs" / "A01.json").read_text()


def ok(text=RAW, tokens=1500):
    return 200, json.dumps({"choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {"total_tokens": tokens}}).encode(), {}


def err(status, headers=None, msg="x"):
    return status, json.dumps({"error": {"code": "rate_limit_exceeded", "message": msg}}).encode(), headers or {}


def make(replies, **kw):
    seq, sleeps, calls = list(replies), [], []
    def t(url, headers, body):
        calls.append(body)
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    kw.setdefault("retry", RetryPolicy())
    return GroqExtractor(model="openai/gpt-oss-120b", api_key="k", transport=t, sleep=sleeps.append, rng=random.Random(1), **kw), sleeps, calls


class Retries(unittest.TestCase):
    def test_429_with_retry_after_waits_the_requested_time_then_succeeds(self):
        ex, sleeps, calls = make([err(429, {"Retry-After": "7"}), ok()])
        self.assertTrue(ex.extract(ART["A01"]).text)
        self.assertEqual(len(calls), 2)
        self.assertGreaterEqual(sleeps[0], 7.0)
        self.assertLess(sleeps[0], 8.1)

    def test_429_without_retry_after_uses_exponential_backoff_with_jitter(self):
        ex, sleeps, _ = make([err(429), err(429), err(429), ok()])
        ex.extract(ART["A01"])
        self.assertEqual(len(sleeps), 3)
        for n, s in enumerate(sleeps):
            base = 2.0 * 2 ** n
            self.assertTrue(base <= s <= base * 1.25 + 1e-9, (n, s))
        self.assertTrue(sleeps[0] < sleeps[1] < sleeps[2])

    def test_backoff_is_capped(self):
        self.assertLessEqual(RetryPolicy().backoff(20, random.Random(0)), 60 * 1.25)

    def test_groq_message_hint_is_used_when_no_header(self):
        self.assertAlmostEqual(parse_retry_after({}, err(429, msg="Please try again in 7.194s.")[1]), 7.194)
        self.assertEqual(parse_retry_after({"Retry-After": "3"}, err(429, msg="try again in 99s")[1]), 3.0)
        self.assertIsNone(parse_retry_after({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}))

    def test_retry_exhaustion_reports_exact_failure_and_attempt_count(self):
        ex, sleeps, calls = make([err(429)] * 6 + [ok()])
        with self.assertRaises(LLMRetryExhausted) as cm:
            ex.extract(ART["A01"])
        self.assertEqual((len(calls), cm.exception.status, cm.exception.attempts), (6, 429, 6))
        self.assertIn("rate_limit_exceeded", str(cm.exception))
        self.assertIn("6 attempt", str(cm.exception))
        self.assertEqual(len(sleeps), 5)

    def test_an_excessive_retry_after_is_reported_not_slept_through(self):
        ex, sleeps, calls = make([err(429, {"Retry-After": "3600"}), ok()])
        with self.assertRaises(LLMRetryExhausted):
            ex.extract(ART["A01"])
        self.assertEqual((sleeps, len(calls)), ([], 1))

    def test_5xx_is_retried_separately_and_fewer_times(self):
        ex, sleeps, calls = make([err(503), ok()])
        ex.extract(ART["A01"])
        self.assertEqual(len(calls), 2)
        ex, sleeps, calls = make([err(500)] * 5)
        with self.assertRaises(LLMRetryExhausted) as cm:
            ex.extract(ART["A01"])
        self.assertEqual((len(calls), cm.exception.status), (3, 500))

    def test_network_errors_are_transient_and_bounded(self):
        ex, _, calls = make([TimeoutError("t"), ok()])
        ex.extract(ART["A01"])
        ex, _, calls = make([OSError("dns")] * 4)
        with self.assertRaises(LLMRetryExhausted):
            ex.extract(ART["A01"])
        self.assertEqual(len(calls), 3)

    def test_non_retryable_errors_make_exactly_one_request(self):
        for status in (400, 401, 403, 404):
            ex, sleeps, calls = make([err(status), ok()])
            with self.assertRaises(LLMError) as cm:
                ex.extract(ART["A01"])
            self.assertNotIsInstance(cm.exception, LLMRetryExhausted)
            self.assertEqual((len(calls), sleeps, cm.exception.status), (1, [], status))

    def test_schema_or_format_errors_are_not_retried(self):
        ex, sleeps, calls = make([(200, b"not json", {}), ok()])
        with self.assertRaises(LLMError):
            ex.extract(ART["A01"])
        self.assertEqual(len(calls), 1)
        ex, _, calls = make([ok("   "), ok()])
        with self.assertRaises(LLMError):
            ex.extract(ART["A01"])
        self.assertEqual(len(calls), 1)

    def test_two_tuple_legacy_transports_still_work(self):
        ex = GroqExtractor(model="openai/gpt-oss-120b", api_key="k", transport=lambda u, h, b: (200, ok()[1]), sleep=lambda s: None)
        self.assertTrue(ex.extract(ART["A01"]).text)


class FakeLive:
    KIND, model, reasoning_effort = "GROQ_API", "openai/gpt-oss-120b", "low"
    def __init__(self, fail_on=None, status=429):
        self.calls, self.fail_on, self.status, self.last_usage_tokens, self.last_attempts = [], fail_on, status, 1000, 1
    def extract(self, a):
        self.calls.append(a.artifact_id)
        if a.artifact_id == self.fail_on:
            raise LLMRetryExhausted("Groq API returned HTTP 429 (rate limited) Gave up after 6 attempt(s).", self.status, 6, True)
        raw = (ROOT / "eval" / "recorded_outputs" / f"{a.artifact_id}.json").read_text()
        return RawExtraction(raw, "GROQ_API", self.model, "p", "r")


class ResumeAndCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.arts = EV.load_corpus()
        self.cache = LiveCache(Path(self.tmp.name))
        self.log = []

    def collect(self, live, cache="default"):
        return EV.collect_live(self.arts, live, self.cache if cache == "default" else cache, self.log.append, sleep=lambda s: None)

    def test_partial_run_keeps_successes_and_reports_failure_and_remaining(self):
        fail_id = self.arts[5].artifact_id
        live = FakeLive(fail_on=fail_id)
        got = self.collect(live)
        self.assertEqual(len(got["raws"]), 5)
        self.assertEqual([f["artifact_id"] for f in got["failed"]], [fail_id])
        self.assertEqual(len(got["not_attempted"]), len(self.arts) - 6)
        self.assertNotIn(fail_id, got["raws"])
        self.assertEqual(len(live.calls), 6, "aborts after exhausted rate-limit retries instead of hammering the API")

    def test_resume_reuses_cache_and_makes_no_duplicate_requests(self):
        self.collect(FakeLive(fail_on=self.arts[5].artifact_id))
        live2 = FakeLive()
        got = self.collect(live2)
        self.assertEqual(len(got["raws"]), len(self.arts))
        self.assertEqual(live2.calls, [a.artifact_id for a in self.arts[5:]])
        self.assertEqual(sum(v == "cache" for v in got["source"].values()), 5)
        live3 = FakeLive()
        self.collect(live3)
        self.assertEqual(live3.calls, [])
        self.assertTrue(any("CACHED" in l for l in self.log) and any("FRESH API call" in l for l in self.log))

    def test_cache_is_not_reused_across_model_prompt_or_schema_changes(self):
        a = self.arts[0]
        base = cache_meta(a.sha256, "GROQ_API", "openai/gpt-oss-120b", "low")
        self.cache.put(base, RawExtraction("{}", "GROQ_API", "openai/gpt-oss-120b"))
        self.assertIsNotNone(self.cache.get(base))
        for other in (cache_meta(a.sha256, "GROQ_API", "openai/gpt-oss-20b", "low"), cache_meta(a.sha256, "GROQ_API", "openai/gpt-oss-120b", "high"),
                      cache_meta(a.sha256, "GROQ_API", "openai/gpt-oss-120b", "low", prompt_sha="0" * 64),
                      cache_meta(a.sha256, "GROQ_API", "openai/gpt-oss-120b", "low", prompt_version="extraction-prompt-2"),
                      cache_meta(a.sha256, "GROQ_API", "openai/gpt-oss-120b", "low", schema_fp="1" * 64),
                      cache_meta("f" * 64, "GROQ_API", "openai/gpt-oss-120b", "low")):
            self.assertIsNone(self.cache.get(other))
        self.assertEqual(len(schema_fingerprint()), 64)

    def test_a_different_model_triggers_fresh_calls_for_every_artifact(self):
        self.collect(FakeLive())
        other = FakeLive()
        other.model = "openai/gpt-oss-20b"
        self.collect(other)
        self.assertEqual(len(other.calls), len(self.arts))

    def test_corrupt_or_tampered_cache_entries_are_ignored(self):
        a = self.arts[0]
        meta = cache_meta(a.sha256, "GROQ_API", "openai/gpt-oss-120b", "low")
        self.cache.put(meta, RawExtraction("{}", "GROQ_API", "m"))
        f = next(Path(self.tmp.name).glob("*.json"))
        f.write_text("{broken")
        self.assertIsNone(self.cache.get(meta))

    def test_failed_artifacts_are_never_cached(self):
        self.collect(FakeLive(fail_on=self.arts[0].artifact_id))
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])

    def test_auth_failure_aborts_remaining_artifacts(self):
        live = FakeLive(fail_on=self.arts[1].artifact_id)
        live.extract = lambda a, _o=live.extract: (_ for _ in ()).throw(LLMError("HTTP 401", 401, 1)) if a.artifact_id == self.arts[1].artifact_id else _o(a)
        got = self.collect(live)
        self.assertEqual(len(got["not_attempted"]), len(self.arts) - 2)


class Cli(unittest.TestCase):
    def test_help_prints_usage_and_makes_no_request_and_writes_nothing(self):
        before = (ROOT / "eval" / "results.json").read_bytes()
        buf = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            EV.main(["--help"], live_factory=lambda e: self.fail("must not build an extractor"))
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--live", buf.getvalue())
        self.assertNotIn("PASS", buf.getvalue())
        self.assertEqual((ROOT / "eval" / "results.json").read_bytes(), before)

    def test_default_run_is_still_the_recorded_replay(self):
        lines = []
        rc = EV.main([], out=lines.append)
        self.assertEqual(rc, 0)
        self.assertTrue(any("RECORDED" in l for l in lines))

    def test_live_without_configuration_exits_2_without_requests(self):
        lines = []
        self.assertEqual(EV.main(["--live"], env={}, out=lines.append), 2)

    def test_partial_live_run_exits_3_reports_no_metrics_and_never_writes_complete_results(self):
        res = ROOT / "eval" / "results_live.json"
        existed = res.exists()
        with tempfile.TemporaryDirectory() as d:
            lines = []
            live = FakeLive(fail_on=EV.load_corpus()[3].artifact_id)
            rc = EV.main(["--live", "--cache-dir", d], live_factory=lambda e: live, out=lines.append)
            self.assertEqual(rc, 3)
            text = "\n".join(lines)
            self.assertIn("INCOMPLETE LIVE EVALUATION", text)
            self.assertNotIn("ALL PASS", text)
            self.assertNotIn("fact_recall", text)
            part = json.loads((ROOT / "eval" / "results_live_partial.json").read_text())
            self.assertFalse(part["complete"])
            self.assertEqual(res.exists(), existed)
            (ROOT / "eval" / "results_live_partial.json").unlink()

    def test_complete_live_run_reports_fresh_and_cached_counts(self):
        res = ROOT / "eval" / "results_live.json"
        saved = res.read_bytes() if res.exists() else None
        try:
            with tempfile.TemporaryDirectory() as d:
                lines = []
                rc = EV.main(["--live", "--cache-dir", d, "--tpm", "1000000"], live_factory=lambda e: FakeLive(), out=lines.append)
                data = json.loads(res.read_text())
                self.assertTrue(data["run"]["complete"])
                self.assertEqual((data["run"]["fresh_api_calls"], data["run"]["cache_hits"]), (data["artifact_count"], 0))
                self.assertIn(rc, (0, 1))
                lines2, live2 = [], FakeLive()
                EV.main(["--live", "--cache-dir", d], live_factory=lambda e: live2, out=lines2.append)
                self.assertEqual(live2.calls, [])
                self.assertEqual(json.loads(res.read_text())["run"]["fresh_api_calls"], 0)
        finally:
            res.unlink(missing_ok=True)
            if saved is not None:
                res.write_bytes(saved)


if __name__ == "__main__":
    unittest.main()
