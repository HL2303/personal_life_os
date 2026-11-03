import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "diagnose_ai_provider.py"
SPEC = importlib.util.spec_from_file_location("diagnose_ai_provider", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def test_sanitize_error_metadata_omits_provider_message_and_untrusted_values():
    response = {
        "error": {
            "status": "UNAVAILABLE",
            "code": 503,
            "type": "service_unavailable",
            "message": "contains secret and user prompt",
            "details": [
                {"reason": "SERVICE_UNAVAILABLE"},
                {"reason": "unsafe value with spaces"},
            ],
        }
    }

    metadata = diagnostic.sanitize_error_metadata(json.dumps(response).encode())

    assert metadata == {
        "status": "UNAVAILABLE",
        "code": 503,
        "type": "service_unavailable",
        "reason": "SERVICE_UNAVAILABLE",
    }
    assert "secret" not in json.dumps(metadata)
    assert "user prompt" not in json.dumps(metadata)


def test_make_request_uses_fixed_prompt_and_only_requested_parameters():
    request = diagnostic.make_request(
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-3.8-flash",
        "diagnostic-api-key",
        {},
    )
    payload = json.loads(request.data)

    assert request.full_url == (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert payload == {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "Reply with OK."}],
    }
    assert request.get_header("Authorization") == "Bearer diagnostic-api-key"
    assert "diagnostic-api-key" not in json.dumps(payload)


def test_activity_options_probe_matches_parameters_under_investigation():
    request = diagnostic.make_request(
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-3.8-flash",
        "diagnostic-api-key",
        {"temperature": 0, "response_format": {"type": "json_object"}},
    )

    assert json.loads(request.data) == {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def test_http_probe_returns_only_status_and_safe_provider_metadata(monkeypatch):
    error_body = {
        "error": {
            "status": "UNAVAILABLE",
            "code": 503,
            "message": "private api key and user message",
        }
    }
    error = HTTPError(
        "https://provider.test/v1/chat/completions",
        503,
        "Service Unavailable",
        {},
        io.BytesIO(json.dumps(error_body).encode()),
    )

    def fail_request(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(diagnostic, "urlopen", fail_request)
    request = diagnostic.make_request(
        "https://provider.test/v1",
        "gemini-3.8-flash",
        "private-api-key",
        {},
    )

    result = diagnostic.run_probe("minimal", request, 10)

    assert result == {
        "probe": "minimal",
        "http_status": 503,
        "ok": False,
        "provider_error": {"status": "UNAVAILABLE", "code": 503},
    }
    assert "private" not in json.dumps(result)
