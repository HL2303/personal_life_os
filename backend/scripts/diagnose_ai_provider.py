"""Probe the configured OpenAI-compatible endpoint without sending user data.

Run from the backend directory with ``python -m scripts.diagnose_ai_provider``.
The diagnostic sends a baseline request and a second request with the optional
parameters used by activity extraction, then prints only status and safe error metadata.
"""

import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.core.config import settings

SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*")
API_KEY_TOKEN = re.compile(r"\b(?:gsk_[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]+)\b")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_ERROR_MESSAGE_LENGTH = 300
FIXED_MESSAGES = [{"role": "user", "content": "Reply with OK."}]
PROBES = (
    ("minimal", {}),
    (
        "activity_options",
        {"temperature": 0, "response_format": {"type": "json_object"}},
    ),
)


def _safe_token(value: object) -> str | int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and SAFE_TOKEN.fullmatch(value):
        return value
    return None


def _redact_sensitive_text(text: str, sensitive_values: tuple[str, ...]) -> str:
    text = BEARER_TOKEN.sub("[REDACTED]", text)
    text = API_KEY_TOKEN.sub("[REDACTED]", text)
    for value in sorted((value for value in sensitive_values if value), key=len, reverse=True):
        text = re.sub(re.escape(value), "[REDACTED]", text, flags=re.IGNORECASE)
    return CONTROL_CHARACTERS.sub("", text)


def _request_sensitive_values(request: Request) -> tuple[str, ...]:
    values = []
    authorization = request.get_header("Authorization")
    if authorization:
        values.append(authorization)
        if authorization.casefold().startswith("bearer "):
            values.append(authorization[7:])

    try:
        payload = json.loads(request.data or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
        for message in payload["messages"]:
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                values.append(message["content"])
    return tuple(values)


def sanitize_error_metadata(
    response_body: bytes,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> dict[str, str]:
    try:
        body = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = response_body.decode("utf-8", errors="replace")
        text = _redact_sensitive_text(text, sensitive_values)
        sanitized = " ".join(text.split())[:MAX_ERROR_MESSAGE_LENGTH]
        return {"message": sanitized or "Unparseable provider error response."}

    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {"message": "Provider returned an unrecognized error response."}

    metadata: dict[str, str] = {}
    message = error.get("message")
    if isinstance(message, str):
        safe_message = _redact_sensitive_text(message, sensitive_values)
        safe_message = " ".join(safe_message.split())[:MAX_ERROR_MESSAGE_LENGTH]
        if safe_message:
            metadata["message"] = safe_message
    for field in ("type", "code"):
        value = error.get(field)
        if value is not None:
            safe_value = _safe_token(value)
            if isinstance(safe_value, (str, int)):
                metadata[field] = str(safe_value)
    return metadata


def make_request(
    base_url: str,
    model: str,
    api_key: str,
    optional_parameters: dict,
) -> Request:
    payload = {"model": model, "messages": FIXED_MESSAGES, **optional_parameters}
    return Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )


def run_probe(name: str, request: Request, timeout: int) -> dict:
    try:
        with urlopen(request, timeout=timeout) as response:
            return {"probe": name, "http_status": response.status, "ok": True}
    except HTTPError as exc:
        try:
            error_body = exc.read()
        except OSError:
            error_body = b""
        result = {
            "probe": name,
            "http_status": exc.code,
            "ok": False,
            "provider_error": sanitize_error_metadata(
                error_body,
                sensitive_values=_request_sensitive_values(request),
            ),
        }
        return result
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "probe": name,
            "ok": False,
            "transport_error_type": type(exc).__name__,
        }


def main() -> int:
    api_key = settings.ai_api_key.get_secret_value() if settings.ai_api_key else ""
    if settings.ai_provider != "openai_compatible":
        print("Diagnostic not run: AI_PROVIDER must be openai_compatible.")
        return 2
    if not api_key:
        print("Diagnostic not run: AI_API_KEY is not configured.")
        return 2

    results = []
    for name, parameters in PROBES:
        request = make_request(
            settings.ai_base_url,
            settings.ai_model,
            api_key,
            parameters,
        )
        results.append(
            run_probe(name, request, settings.ai_request_timeout_seconds)
        )

    print(
        json.dumps(
            {
                "model": settings.ai_model,
                "endpoint_host": urlsplit(settings.ai_base_url).hostname,
                "results": results,
            },
            separators=(",", ":"),
        )
    )
    return 0 if all(result.get("ok") for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
