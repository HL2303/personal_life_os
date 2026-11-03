import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import settings


class TelegramAPIError(Exception):
    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def send_message(chat_id: int, text: str) -> int | None:
    if settings.telegram_bot_token is None:
        raise TelegramAPIError("Telegram bot is not configured.")
    token = settings.telegram_bot_token.get_secret_value()
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            data = json.loads(response.read())
    except HTTPError as exc:
        try:
            data = json.loads(exc.read())
            params = data.get("parameters", {})
            retry_after = params.get("retry_after")
            description = data.get("description", "Telegram rejected the request.")
        except (json.JSONDecodeError, AttributeError):
            retry_after = None
            description = "Telegram API request failed."
        raise TelegramAPIError(description, retry_after=retry_after) from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise TelegramAPIError("Telegram API is temporarily unavailable.") from None
    if not data.get("ok"):
        raise TelegramAPIError("Telegram API rejected the message.")
    result = data.get("result", {})
    message_id = result.get("message_id")
    return message_id if isinstance(message_id, int) else None
