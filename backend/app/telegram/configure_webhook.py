import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app.core.config import settings


def configure_webhook() -> None:
    if (
        settings.telegram_bot_token is None
        or not settings.telegram_bot_token.get_secret_value()
        or settings.telegram_webhook_secret is None
        or not settings.telegram_webhook_secret.get_secret_value()
        or not settings.telegram_webhook_url
    ):
        raise RuntimeError(
            "Set TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, and "
            "TELEGRAM_WEBHOOK_URL before configuring the webhook."
        )
    webhook_url = urlsplit(settings.telegram_webhook_url)
    if (
        webhook_url.scheme != "https"
        or not webhook_url.hostname
        or webhook_url.username
        or webhook_url.password
    ):
        raise RuntimeError("TELEGRAM_WEBHOOK_URL must use a public HTTPS origin.")
    request = Request(
        "https://api.telegram.org/bot"
        f"{settings.telegram_bot_token.get_secret_value()}/setWebhook",
        data=json.dumps(
            {
                "url": settings.telegram_webhook_url.rstrip("/") + "/api/telegram/webhook",
                "secret_token": settings.telegram_webhook_secret.get_secret_value(),
                "allowed_updates": ["message"],
                "drop_pending_updates": False,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Telegram webhook registration failed ({type(exc).__name__})."
        ) from None
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected webhook registration.")
    print("Telegram webhook registered.")


if __name__ == "__main__":
    try:
        configure_webhook()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
