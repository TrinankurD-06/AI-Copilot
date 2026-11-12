from app.core.config import Settings
from app.integrations.llm.gateway import LLMGateway
from app.integrations.llm.providers import ProviderError, RateLimited, Transient


class Fake:
    def __init__(self, name, outcomes):
        self.name, self.model, self.outcomes, self.calls = name, "m", list(outcomes), 0

    def complete(self, prompt, *, json_mode):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def gateway(*providers):
    cfg = Settings(LLM_MAX_RETRIES=2, LLM_SCHEMA_REPAIR_ATTEMPTS=1)
    return LLMGateway(cfg, providers=list(providers))


def test_first_provider_wins():
    a, b = Fake("a", ["{}"]), Fake("b", ["{}"])
    c = gateway(a, b).complete("hi", json_mode=True)
    assert (c.provider, b.calls) == ("a", 0)


def test_rate_limited_skips_to_next_without_retry(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    a, b = Fake("a", [RateLimited("quota")]), Fake("b", ['{"ok":1}'])
    c = gateway(a, b).complete("hi", json_mode=True)
    assert (c.provider, a.calls) == ("b", 1)


def test_transient_is_retried_then_falls_through(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    a, b = Fake("a", [Transient("503"), Transient("503")]), Fake("b", ["{}"])
    c = gateway(a, b).complete("hi", json_mode=True)
    assert (c.provider, a.calls) == ("b", 2)


def test_all_fail_raises(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    try:
        gateway(Fake("a", [ProviderError("400")])).complete("hi")
    except RuntimeError as e:
        assert "all LLM providers failed" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_parse_json_strips_fences_and_rejects_non_objects():
    assert LLMGateway.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    for bad in ("[1,2]", "not json"):
        try:
            LLMGateway.parse_json(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)


def test_refusal_stops_the_chain(monkeypatch):
    from app.integrations.llm.providers import Refused

    monkeypatch.setattr("time.sleep", lambda s: None)
    a, b = Fake("a", [Refused("declined")]), Fake("b", ['{"nodes": []}'])
    try:
        gateway(a, b).complete("rm -rf /", json_mode=True)
    except Refused:
        pass
    else:
        raise AssertionError("expected Refused to propagate")
    assert (a.calls, b.calls) == (1, 0)


def test_groq_json_validate_failed_is_a_refusal():
    from app.integrations.llm.providers import _refusal_from_error_body

    body = {"error": {"code": "json_validate_failed", "failed_generation": "I can't comply."}}
    assert _refusal_from_error_body(body) == "I can't comply."
    assert _refusal_from_error_body({"error": {"code": "other"}}) is None
    assert _refusal_from_error_body("not a dict") is None



def test_openai_compatible_empty_choices_is_transient():
    from types import SimpleNamespace
    from app.integrations.llm.providers import OpenAICompatibleProvider, Transient

    prov = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    prov.name, prov.model = "x", "m"
    prov._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(choices=[]))))
    try:
        prov.complete("hi", json_mode=True)
    except Transient:
        pass
    else:
        raise AssertionError("expected Transient")


def test_gemini_non_stop_finish_reason_is_a_refusal():
    from types import SimpleNamespace
    from app.integrations.llm.providers import GeminiProvider, Refused

    for reason in ("FinishReason.SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
        prov = GeminiProvider.__new__(GeminiProvider)
        prov.model = "m"
        resp = SimpleNamespace(text="", prompt_feedback=None,
                               candidates=[SimpleNamespace(finish_reason=reason)])
        prov._client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: resp))
        try:
            prov.complete("hi", json_mode=True)
        except Refused:
            continue
        raise AssertionError(reason)
