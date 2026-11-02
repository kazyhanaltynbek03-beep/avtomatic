"""Encrypted server-side credentials for workspace-level integrations."""
import base64
import hashlib
import json
import os

from cryptography.fernet import Fernet, InvalidToken

from .db import SessionLocal
from .models import SystemIntegrationSecret


class SecretStorageError(RuntimeError):
    pass


def _fernet():
    material = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if not material:
        if os.getenv("APP_ENV", "development").lower() == "production":
            raise SecretStorageError("На сервере не задан CREDENTIAL_ENCRYPTION_KEY")
        material = os.getenv("OWNER_PASSWORD") or os.getenv("DATABASE_URL", "qor-local-dev")
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)


def load_config(provider, db=None):
    def read(session):
        row = session.get(SystemIntegrationSecret, provider)
        if not row:
            return {}
        try:
            payload = _fernet().decrypt(row.encrypted_payload.encode()).decode()
            result = json.loads(payload)
        except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
            raise SecretStorageError(
                "Не удалось расшифровать ключ интеграции. "
                "Проверьте CREDENTIAL_ENCRYPTION_KEY на сервере."
            ) from exc
        return result if isinstance(result, dict) else {}

    if db is not None:
        return read(db)
    with SessionLocal() as session:
        return read(session)


def save_config(db, provider, config):
    try:
        encrypted = _fernet().encrypt(
            json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode()
        ).decode()
    except SecretStorageError:
        raise
    row = db.get(SystemIntegrationSecret, provider)
    if row is None:
        row = SystemIntegrationSecret(provider=provider, encrypted_payload=encrypted)
        db.add(row)
    else:
        row.encrypted_payload = encrypted
    row.key_hint = str(config.get("api_key") or config.get("access_token") or "")[-6:]
    db.flush()


def delete_config(db, provider):
    row = db.get(SystemIntegrationSecret, provider)
    if row is not None:
        db.delete(row)
        db.flush()
