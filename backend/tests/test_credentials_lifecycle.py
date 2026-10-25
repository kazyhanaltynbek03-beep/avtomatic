"""Direct regression coverage for encrypted per-account marketplace credentials."""

from sqlalchemy import select
import pytest

from app import main
from app.connectors import AccessRequired, load_saved_credentials
from app.db import Base, SessionLocal, engine
from app.models import Account, Company, IntegrationSecret, User


def test_credentials_create_replace_delete_and_recreate_without_conflict(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OWNER_PASSWORD", "development-only-test-secret")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        db.add_all([
            Company(id=1, name="Credentials", bin="000000000001"),
            User(id=1, email="owner@credentials.kz", name="Owner", password_hash="x", role="Owner"),
        ])
        db.commit()
        db.add(Account(id=1, company_id=1, name="WB", channel="Wildberries", mode="csv"))
        db.commit()
        owner = db.get(User, 1)

        first = main.save_account_credentials(1, {"token": "first-token-1234"}, owner, db)
        assert first["configured"] is True
        assert "first-token" not in str(first)
        assert load_saved_credentials(db, 1) == {"token": "first-token-1234"}

        second = main.save_account_credentials(1, {"token": "replacement-token-5678"}, owner, db)
        assert second["configured"] is True
        assert len(db.scalars(select(IntegrationSecret).where(IntegrationSecret.account_id == 1)).all()) == 1
        assert load_saved_credentials(db, 1) == {"token": "replacement-token-5678"}

        # A Render encryption-key mismatch must be explicit; an empty token
        # would otherwise look like a Wildberries permission failure.
        monkeypatch.setenv("OWNER_PASSWORD", "wrong-encryption-key")
        with pytest.raises(AccessRequired, match="расшифровать сохранённый токен"):
            load_saved_credentials(db, 1)
        monkeypatch.setenv("OWNER_PASSWORD", "development-only-test-secret")

        assert main.delete_account_credentials(1, owner, db) == {"ok": True, "archived": True}
        assert db.get(Account, 1).active is False
        assert load_saved_credentials(db, 1) == {}
        main.save_account_credentials(1, {"token": "recreated-token-9012"}, owner, db)
        assert db.get(Account, 1).active is True
        assert len(db.scalars(select(IntegrationSecret).where(IntegrationSecret.account_id == 1)).all()) == 1
        assert load_saved_credentials(db, 1) == {"token": "recreated-token-9012"}
    finally:
        db.close()


def test_integration_secret_model_has_no_orphan_updated_at_column():
    """Regression: production migration schema must match the ORM credential model."""
    from app.models import IntegrationSecret
    assert "updated_at" not in IntegrationSecret.__table__.columns
    assert {"id", "created_at", "account_id", "encrypted_payload", "key_hint"}.issubset(
        set(IntegrationSecret.__table__.columns.keys())
    )
