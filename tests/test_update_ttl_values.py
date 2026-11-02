import pytest

from opencode_go_proxy.updates import DEFAULT_TTL_SECONDS, TTL_HOURS_ENV, _ttl_seconds


@pytest.mark.parametrize("value", ["nan", "inf", "1e309", "1e308"])
def test_nonfinite_or_overflowing_ttl_uses_default(monkeypatch, value):
    monkeypatch.setenv(TTL_HOURS_ENV, value)
    assert _ttl_seconds() == DEFAULT_TTL_SECONDS
