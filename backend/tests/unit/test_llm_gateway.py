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
