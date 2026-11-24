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
            "message": "contains actual-secret and private prompt",
            "details": [
                {"reason": "SERVICE_UNAVAILABLE"},
                {"reason": "unsafe value with spaces"},
            ],
        }
    }

    metadata = diagnostic.sanitize_error_metadata(
        json.dumps(response).encode(),
        sensitive_values=("actual-secret", "private prompt"),
    )

    assert metadata == {
        "message": "contains [REDACTED] and [REDACTED]",
        "type": "service_unavailable",
        "code": "503",
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
    api_key = "private-api-key"
    error_body = {
        "error": {
            "status": "UNAVAILABLE",
            "code": 503,
            "message": f"Rejected: {api_key}; prompt=Reply with OK.",
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
        api_key,
        {},
    )

    result = diagnostic.run_probe("minimal", request, 10)

    assert result == {
        "probe": "minimal",
        "http_status": 503,
        "ok": False,
        "provider_error": {"message": "Rejected: [REDACTED]; prompt=[REDACTED]", "code": "503"},
    }
    assert api_key not in json.dumps(result)
    assert "Reply with OK." not in json.dumps(result)


def test_groq_403_error_exposes_message_type_and_code_without_secrets(monkeypatch):
    api_key = "gsk_diagnostic_secret_value"
    error_body = {
        "error": {
            "message": (
                "Access denied for model openai/gpt-oss-20b. "
                f"Request used Bearer {api_key}."
            ),
            "type": "model_access_error",
            "code": "model_not_allowed",
            "request": {"messages": [{"content": "Reply with OK."}]},
        }
    }
    error = HTTPError(
        "https://api.groq.com/openai/v1/chat/completions",
        403,
        "Forbidden",
        {},
        io.BytesIO(json.dumps(error_body).encode()),
    )

    def fail_request(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(diagnostic, "urlopen", fail_request)
    request = diagnostic.make_request(
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-20b",
        api_key,
        {},
    )

    result = diagnostic.run_probe("minimal", request, 10)

    assert result == {
        "probe": "minimal",
        "http_status": 403,
        "ok": False,
        "provider_error": {
            "message": (
                "Access denied for model openai/gpt-oss-20b. Request used [REDACTED]"
            ),
            "type": "model_access_error",
            "code": "model_not_allowed",
        },
    }
    serialized = json.dumps(result)
    assert api_key not in serialized
    assert "Reply with OK." not in serialized
    assert "messages" not in serialized


def test_non_json_error_body_is_truncated_and_redacted(monkeypatch):
    api_key = "gsk_diagnostic_secret_value"
    body = (
        f"Access denied. Authorization: Bearer {api_key}. "
        "Reply with OK. "
        + ("x" * 500)
    ).encode()
    error = HTTPError(
        "https://api.groq.com/openai/v1/chat/completions",
        403,
        "Forbidden",
        {},
        io.BytesIO(body),
    )

    def fail_request(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(diagnostic, "urlopen", fail_request)
    request = diagnostic.make_request(
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-20b",
        api_key,
        {},
    )

    result = diagnostic.run_probe("minimal", request, 10)

    message = result["provider_error"]["message"]
    assert len(message) <= diagnostic.MAX_ERROR_MESSAGE_LENGTH
    assert "gsk_diagnostic_secret_value" not in message
    assert "Reply with OK." not in message
    assert "Bearer" not in message
    assert "[REDACTED]" in message
