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


def sanitize_error_metadata(response_body: bytes) -> dict[str, str | int]:
    try:
        body = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}

    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {}

    metadata: dict[str, str | int] = {}
    for field in ("status", "code", "type"):
        value = _safe_token(error.get(field))
        if value is not None:
            metadata[field] = value

    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict):
                reason = _safe_token(detail.get("reason"))
                if reason is not None:
                    metadata.setdefault("reason", reason)
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
            "provider_error": sanitize_error_metadata(error_body),
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
