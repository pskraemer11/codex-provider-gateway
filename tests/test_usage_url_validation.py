import pytest

from opencode_go_proxy import usage_poller
from opencode_go_proxy.secrets import clear_api_key_cache


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "https://[invalid",
        "https://example.com:abc/a",
        "https://example.com/\nbad",
    ],
)
def test_invalid_usage_url_degrades_to_unknown(monkeypatch, url):
    monkeypatch.delenv("OPENCODE_GO_PROXY_API_KEY_ENV", raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENCODE_GO_USAGE_URL", url)
    usage_poller.clear_cache()
    clear_api_key_cache()
    try:
        assert usage_poller.poll_go_usage() is None
    finally:
        usage_poller.clear_cache()
        clear_api_key_cache()
