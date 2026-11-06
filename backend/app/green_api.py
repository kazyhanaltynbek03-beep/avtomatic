"""Small, validated GREEN-API client used by WhatsApp chat and reports."""
import logging
import re
from urllib.parse import quote, urlsplit

import httpx

from .system_secrets import load_config

logger = logging.getLogger(__name__)
_INSTANCE_RE = re.compile(r"^\d{1,12}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~-]{8,512}$")


def _credentials(config):
    base_url = str(config.get("green_api_url") or "").strip().rstrip("/")
    instance_id = str(config.get("green_api_instance_id") or "").strip()
    token = str(config.get("green_api_token") or "").strip()
    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or not host.endswith(".api.greenapi.com")
            or parsed.username or parsed.password or parsed.port
            or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError("Укажите HTTPS API URL Green-API, например https://7103.api.greenapi.com")
    if not _INSTANCE_RE.fullmatch(instance_id):
        raise RuntimeError("ID инстанса Green-API должен содержать от 1 до 12 цифр")
    if not _TOKEN_RE.fullmatch(token):
        raise RuntimeError("Проверьте токен инстанса Green-API")
    return base_url, instance_id, token


def _url(config, method):
    base_url, instance_id, token = _credentials(config)
    return f"{base_url}/waInstance{instance_id}/{method}/{quote(token, safe='')}"


def send_text(db, recipient, message):
    """Send a text message to one direct chat, never a group."""
    config = load_config("whatsapp_cloud", db)
    chat_id = str(recipient or "").strip()
    if not chat_id.endswith("@c.us"):
        digits = "".join(char for char in chat_id if char.isdigit())
        chat_id = f"{digits}@c.us" if 8 <= len(digits) <= 15 else ""
    if not re.fullmatch(r"\d{8,15}@c\.us", chat_id):
        raise RuntimeError("Green-API поддерживает ответы только в личный чат WhatsApp")
    try:
        response = httpx.post(
            _url(config, "sendMessage"),
            json={"chatId": chat_id, "message": str(message)[:4096]},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        logger.warning("Green-API sendMessage transport error (%s)", type(exc).__name__)
        raise RuntimeError("Не удалось соединиться с Green-API") from None
    if response.is_error:
        logger.warning("Green-API sendMessage failed with HTTP %s", response.status_code)
        raise RuntimeError(f"Green-API не отправил сообщение (HTTP {response.status_code})")
    try:
        return response.json()
    except ValueError:
        raise RuntimeError("Green-API вернул некорректный ответ") from None


def test_connection(db):
    config = load_config("whatsapp_cloud", db)
    try:
        response = httpx.get(_url(config, "getStateInstance"), timeout=15)
    except httpx.HTTPError as exc:
        logger.warning("Green-API getStateInstance transport error (%s)", type(exc).__name__)
        raise RuntimeError("Не удалось соединиться с Green-API") from None
    if response.is_error:
        logger.warning("Green-API getStateInstance failed with HTTP %s", response.status_code)
        raise RuntimeError(f"Green-API ответил HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError("Green-API вернул некорректный ответ") from None
    state = str(body.get("stateInstance") or "unknown")
    return {"ok": state == "authorized", "state": state,
            "message": "Инстанс Green-API авторизован" if state == "authorized" else f"Состояние инстанса: {state}"}
