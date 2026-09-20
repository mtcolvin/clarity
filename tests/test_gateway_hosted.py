"""
Phase (c) of the Phase B export arc — the real Anthropic _hosted_call
(CLAUDE.md "The export handoff", ROADMAP.md #1 "PLAN OF RECORD"). All network
I/O is mocked at the urllib.request.urlopen boundary — hermetic, no live
ANTHROPIC_API_KEY dependence, no real request ever leaves the machine in this
suite. The one-time dry-run + first-send byte-compare are manual ceremonies
(see the phase (c) handoff), not suite tests — a live key would defeat the
"no CI dependence on a real provider" property this file is built to have.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

import gateway
from gateway import LLMRequest, complete


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_success(monkeypatch, body_dict, api_key="sk-ant-test"):
    monkeypatch.setenv(gateway._ANTHROPIC_API_KEY_ENV, api_key)
    monkeypatch.setattr(
        gateway.urllib.request, "urlopen",
        lambda req, timeout=60: _FakeResponse(json.dumps(body_dict).encode("utf-8")),
    )


def _stub_http_error(monkeypatch, code, api_key="sk-ant-test"):
    monkeypatch.setenv(gateway._ANTHROPIC_API_KEY_ENV, api_key)

    def _raise(req, timeout=60):
        raise urllib.error.HTTPError(url="https://api.anthropic.com/v1/messages",
                                     code=code, msg="err", hdrs=None, fp=None)
    monkeypatch.setattr(gateway.urllib.request, "urlopen", _raise)


# --------------------------------------------------------------- _anthropic_call

def test_anthropic_call_success(monkeypatch):
    _stub_success(monkeypatch, {
        "content": [{"type": "text", "text": "Nothing here stands out to interpret."}],
        "model": "claude-sonnet-5",
    })
    text, model = gateway._anthropic_call([{"metric": "m"}], "system prompt")
    assert text == "Nothing here stands out to interpret."
    assert model == "claude-sonnet-5"


def test_anthropic_call_concatenates_multiple_text_blocks(monkeypatch):
    _stub_success(monkeypatch, {
        "content": [{"type": "text", "text": "Part one. "}, {"type": "text", "text": "Part two."}],
        "model": "claude-sonnet-5",
    })
    text, _ = gateway._anthropic_call([{"metric": "m"}], "system prompt")
    assert text == "Part one. Part two."


def test_anthropic_call_missing_api_key(monkeypatch):
    monkeypatch.delenv(gateway._ANTHROPIC_API_KEY_ENV, raising=False)
    with pytest.raises(gateway.HostedCallError, match="ANTHROPIC_API_KEY is not set"):
        gateway._anthropic_call([{"metric": "m"}], "system prompt")


def test_anthropic_call_empty_response_raises(monkeypatch):
    _stub_success(monkeypatch, {"content": [], "model": "claude-sonnet-5"})
    with pytest.raises(gateway.HostedCallError, match="empty response"):
        gateway._anthropic_call([{"metric": "m"}], "system prompt")


def test_anthropic_call_truncated_response_raises(monkeypatch):
    """A cut-off response (stop_reason max_tokens) must fail cleanly rather
    than silently return a mid-sentence fragment as if it were complete —
    found live: claude-sonnet-5's adaptive thinking draws from the same
    max_tokens budget as the visible text, so a generation that thinks more
    than usual can truncate the response without any HTTP error at all."""
    _stub_success(monkeypatch, {
        "content": [{"type": "text", "text": "This looks fine but is cut off mid-"}],
        "model": "claude-sonnet-5", "stop_reason": "max_tokens",
    })
    with pytest.raises(gateway.HostedCallError, match="cut off"):
        gateway._anthropic_call([{"metric": "m"}], "system prompt")


@pytest.mark.parametrize("code,fragment", [
    (401, "unauthorized"),
    (402, "billing"),
    (429, "rate-limiting"),
    (500, "temporarily unavailable"),
    (503, "temporarily unavailable"),
])
def test_anthropic_call_http_errors_map_cleanly(monkeypatch, code, fragment):
    _stub_http_error(monkeypatch, code)
    with pytest.raises(gateway.HostedCallError, match=fragment):
        gateway._anthropic_call([{"metric": "m"}], "system prompt")


def test_anthropic_call_network_error(monkeypatch):
    monkeypatch.setenv(gateway._ANTHROPIC_API_KEY_ENV, "sk-ant-test")

    def _raise(req, timeout=60):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(gateway.urllib.request, "urlopen", _raise)
    with pytest.raises(gateway.HostedCallError, match="Network error"):
        gateway._anthropic_call([{"metric": "m"}], "system prompt")


def test_anthropic_call_read_timeout_maps_cleanly(monkeypatch):
    """A timeout while READING the response raises a bare TimeoutError, not a URLError
    (only a CONNECT timeout is wrapped). It used to escape every handler and surface as
    an unhandled 500 with no CORS headers — an opaque browser "NetworkError" — while
    writing NO audit entry despite the send having been attempted. Observed live on a
    full-picture export once the payload grew past what 60s could generate."""
    monkeypatch.setenv(gateway._ANTHROPIC_API_KEY_ENV, "sk-ant-test")

    def _raise(req, timeout=None):
        raise TimeoutError("timed out")
    monkeypatch.setattr(gateway.urllib.request, "urlopen", _raise)
    with pytest.raises(gateway.HostedCallError, match="did not respond in time"):
        gateway._anthropic_call([{"metric": "m"}], "system prompt")


def test_read_timeout_is_audited_as_an_attempted_send(monkeypatch, tmp_path):
    """The charter's transparency rule: bytes that LEFT the machine must leave a durable
    local record even when the call fails. Before the TimeoutError catch, a timeout
    produced silent egress — no audit line at all."""
    monkeypatch.setenv(gateway._ANTHROPIC_API_KEY_ENV, "sk-ant-test")
    monkeypatch.setattr(gateway, "_AUDIT_LOG", str(tmp_path / "audit.log"))

    def _raise(req, timeout=None):
        raise TimeoutError("timed out")
    monkeypatch.setattr(gateway.urllib.request, "urlopen", _raise)

    fields = [{"metric": "m", "value": 1.0, "unit": "mg/dL"}]
    req = gateway.LLMRequest(task="summarize_labs", engine="hosted",
                             fields=fields, provider="anthropic")
    token = gateway.complete(req).preview.confirmation_token
    result = gateway.complete(req, confirmation=token)

    assert result.status == "provider_error"
    entries = gateway.read_external_audit()
    assert len(entries) == 1
    assert "did not respond in time" in entries[0]["error"]
    assert entries[0]["payload"]  # what left the machine, recorded verbatim


def test_successful_send_returns_the_audit_id_it_wrote(monkeypatch, tmp_path):
    """The join key: complete() hands back the id of the audit entry it just wrote, so a
    caller storing the RESPONSE elsewhere can point at the exact send."""
    _stub_success(monkeypatch, {"content": [{"type": "text", "text": "hi"}],
                                "model": "claude-sonnet-5"})
    monkeypatch.setattr(gateway, "_AUDIT_LOG", str(tmp_path / "audit.log"))
    req = gateway.LLMRequest(task="summarize_labs", engine="hosted",
                             fields=[{"metric": "m", "value": 1.0}], provider="anthropic")
    token = gateway.complete(req).preview.confirmation_token
    result = gateway.complete(req, confirmation=token)

    assert result.status == "ok"
    assert result.audit_id
    entries = gateway.read_external_audit()
    assert entries[0]["id"] == result.audit_id  # points at the entry actually written


def test_audit_ids_are_unique_across_identical_resends(monkeypatch, tmp_path):
    """Why a random id and not a timestamp or payload hash: re-sending the SAME bundle is
    exactly the case worth telling apart, and two entries can share a timestamp."""
    _stub_success(monkeypatch, {"content": [{"type": "text", "text": "hi"}],
                                "model": "claude-sonnet-5"})
    monkeypatch.setattr(gateway, "_AUDIT_LOG", str(tmp_path / "audit.log"))
    req = gateway.LLMRequest(task="summarize_labs", engine="hosted",
                             fields=[{"metric": "m", "value": 1.0}], provider="anthropic")
    token = gateway.complete(req).preview.confirmation_token
    first = gateway.complete(req, confirmation=token).audit_id
    second = gateway.complete(req, confirmation=token).audit_id
    assert first and second and first != second


def test_preview_and_refusal_carry_no_audit_id(monkeypatch, tmp_path):
    """Neither sends, so neither audits — an id on one would imply egress that didn't
    happen, which is precisely the wrong thing for a transparency record to claim."""
    monkeypatch.setattr(gateway, "_AUDIT_LOG", str(tmp_path / "audit.log"))
    req = gateway.LLMRequest(task="summarize_labs", engine="hosted",
                             fields=[{"metric": "m", "value": 1.0}], provider="anthropic")
    assert gateway.complete(req).audit_id is None
    assert gateway.complete(req, confirmation="wrong-token").audit_id is None
    assert gateway.read_external_audit() == []


def test_timeout_is_sized_for_a_full_picture_export():
    """Pins the sizing decision itself: 60s was tuned for a single metric capped at 12
    readings and became a routine failure at full-series scale. A regression to a
    small value would silently reintroduce the failure this test's siblings describe."""
    assert gateway._ANTHROPIC_TIMEOUT_S >= 300


# --------------------------------------------------------------- _hosted_call dispatch

def test_hosted_call_dispatches_to_anthropic(monkeypatch):
    _stub_success(monkeypatch, {"content": [{"type": "text", "text": "ok"}], "model": "claude-sonnet-5"})
    text, model = gateway._hosted_call([{"metric": "m"}], "sys", "anthropic", {})
    assert text == "ok" and model == "claude-sonnet-5"


def test_hosted_call_unwired_provider_fails_honestly():
    with pytest.raises(gateway.HostedCallError, match="openai.*isn't wired"):
        gateway._hosted_call([{"metric": "m"}], "sys", "openai", {})


# --------------------------------------------------------------- complete() integration

def test_complete_provider_error_on_hosted_failure(monkeypatch):
    """A provider failure must never crash complete() or leak a raw exception —
    it becomes a distinct 'provider_error' status, separate from a token-
    mismatch 'refused', with an honest reason."""
    monkeypatch.delenv(gateway._ANTHROPIC_API_KEY_ENV, raising=False)
    fields = [{"metric": "m", "value": 1.0, "unit": "u", "ref_low": 0, "ref_high": 2}]
    preview = complete(LLMRequest(task="summarize_labs", engine="hosted",
                                  fields=fields, provider="anthropic"))
    result = complete(LLMRequest(task="summarize_labs", engine="hosted",
                                 fields=fields, provider="anthropic"),
                      confirmation=preview.preview.confirmation_token)
    assert result.status == "provider_error"
    assert "ANTHROPIC_API_KEY" in result.reason
    assert result.output is None


def test_complete_ok_on_hosted_success(monkeypatch):
    _stub_success(monkeypatch, {"content": [{"type": "text", "text": "Reasoned prose."}],
                                "model": "claude-sonnet-5"})
    fields = [{"metric": "m", "value": 1.0, "unit": "u", "ref_low": 0, "ref_high": 2}]
    preview = complete(LLMRequest(task="summarize_labs", engine="hosted",
                                  fields=fields, provider="anthropic"))
    result = complete(LLMRequest(task="summarize_labs", engine="hosted",
                                 fields=fields, provider="anthropic"),
                      confirmation=preview.preview.confirmation_token)
    assert result.status == "ok"
    assert result.output == "Reasoned prose."
    assert result.model == "claude-sonnet-5"


# --------------------------------------------------------------- config constant

def test_anthropic_model_constant_is_pinned():
    """A future model bump is a deliberate, visible change — this test forces
    updating the pin, not a silent drift. The LIVE-string verification against
    Anthropic's GET /v1/models is a one-time build-time ceremony (see the
    phase (c) handoff), not repeated here — this only pins what the code sends."""
    assert gateway._ANTHROPIC_MODEL == "claude-sonnet-5"
