from http.client import parse_headers
from io import BytesIO

import pytest

from opencode_go_proxy.errors import ProxyError
from opencode_go_proxy.guards import (
    CALLER_TOKEN_ENV,
    CALLER_TOKEN_HEADER,
    REMOTE_ENV,
    check_client,
)


def test_nonascii_supplied_token_is_rejected_instead_of_crashing(monkeypatch):
    monkeypatch.setenv(REMOTE_ENV, "1")
    monkeypatch.setenv(CALLER_TOKEN_ENV, "a" * 32)
    with pytest.raises(ProxyError) as error:
        check_client("192.0.2.1", {CALLER_TOKEN_HEADER: "é" * 32})
    assert error.value.status == 401


def test_configured_unicode_token_uses_actual_http_header_decoding(monkeypatch):
    monkeypatch.setenv(REMOTE_ENV, "1")
    token = "é" * 32
    monkeypatch.setenv(CALLER_TOKEN_ENV, token)
    wire = CALLER_TOKEN_HEADER.encode() + b": " + token.encode("utf-8") + b"\r\n\r\n"
    check_client("192.0.2.1", parse_headers(BytesIO(wire)))


def test_non_http_unicode_header_is_rejected(monkeypatch):
    monkeypatch.setenv(REMOTE_ENV, "1")
    monkeypatch.setenv(CALLER_TOKEN_ENV, "a" * 32)
    with pytest.raises(ProxyError) as error:
        check_client("192.0.2.1", {CALLER_TOKEN_HEADER: "☃" * 32})
    assert error.value.status == 401
