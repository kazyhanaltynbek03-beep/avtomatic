import hashlib, secrets, os
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
try:
    from pwdlib import PasswordHash
    passwords = PasswordHash.recommended()
except ImportError:
    # Compatible fallback for constrained/offline test environments.
    # Production installs pwdlib from backend/requirements.txt.
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    class _Argon2Passwords:
        def __init__(self):
            self._hasher = PasswordHasher()

        def hash(self, password):
            return self._hasher.hash(password)

        def verify(self, password, password_hash):
            try:
                return self._hasher.verify(password_hash, password)
            except VerifyMismatchError:
                return False

    passwords = _Argon2Passwords()
from .db import get_db
from .models import User, Session, Audit, Product, ProductCompany

PERMISSIONS = {
    "Owner": {"*"},
    "Admin": {
        "catalog",
        "inventory",
        "sales",
        "finance",
        "analytics",
        "ai",
        "marketing",
        "documents",
        "imports",
        "accounts",
        "companies",
        "users",
        "audit",
        "settings",
    },
    "Accountant": {
        "finance",
        "analytics",
        "sales:read",
        "catalog:read",
        "inventory:read",
        "companies:read",
        "accounts:read",
        "documents",
        "imports",
    },
    "Manager": {
        "sales",
        "catalog:read",
        "inventory:read",
        "companies:read",
        "accounts:read",
        "documents",
    },
    "Warehouse": {"inventory", "catalog:read", "companies:read", "documents"},
    "Marketing": {
        "documents",
        "marketing",
        "ai:content",
        "catalog:read",
        "companies:read",
        "accounts:read",
    },
}


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get("erp_session")
    if not token:
        raise HTTPException(401, "Войдите в систему")
    sess = db.scalar(select(Session).where(Session.token_hash == digest(token)))
    if not sess or sess.expires_at.replace(tzinfo=timezone.utc) < datetime.now(
        timezone.utc
    ):
        raise HTTPException(401, "Сессия истекла")
    user = db.get(User, sess.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Пользователь отключён")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), token):
            raise HTTPException(403, "CSRF token required")
    return user


def allowed(user, capability, write=False):
    permissions = PERMISSIONS.get(user.role, set())
    return (
        "*" in permissions
        or capability in permissions
        or (not write and capability + ":read" in permissions)
    )


def require(user, capability, write=False):
    if not allowed(user, capability, write):
        raise HTTPException(403, "Недостаточно прав")


def scope(user, company_id):
    if user.role != "Owner" and company_id not in user.company_ids:
        raise HTTPException(403, "Компания недоступна")


def product_company_ids(db, product_id):
    return set(db.scalars(
        select(ProductCompany.company_id).where(ProductCompany.product_id == product_id)
    ).all())


def ensure_product_company(db, product_id, company_id):
    if db.scalar(select(ProductCompany.id).where(
        ProductCompany.product_id == product_id,
        ProductCompany.company_id == company_id,
    )):
        return
    if any(
        isinstance(row, ProductCompany)
        and row.product_id == product_id
        and row.company_id == company_id
        for row in db.new
    ):
        return
    db.add(ProductCompany(product_id=product_id, company_id=company_id))


def require_product_company(db, product_id, company_id):
    if not db.scalar(select(ProductCompany.id).where(
        ProductCompany.product_id == product_id,
        ProductCompany.company_id == company_id,
    )):
        raise HTTPException(422, "Товар не привязан к выбранной компании")


def scope_product(db, user, product_id, company_id=None):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Товар не найден")
    if company_id is not None:
        scope(user, company_id)
        require_product_company(db, product_id, company_id)
    elif user.role != "Owner":
        if not product_company_ids(db, product_id).intersection(set(user.company_ids or [])):
            raise HTTPException(403, "Товар недоступен для выбранных компаний")
    return product


def scope_query(query, model, user):
    if user.role != "Owner":
        if model is Product:
            query = query.where(Product.id.in_(
                select(ProductCompany.product_id).where(
                    ProductCompany.company_id.in_(user.company_ids or [])
                )
            ))
        elif hasattr(model, "company_id"):
            query = query.where(model.company_id.in_(user.company_ids))
    return query


def audit(db, user, action, entity, entity_id=None, details=None):
    db.add(
        Audit(
            user_id=user.id if user else None,
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=jsonable_encoder(details or {}),
        )
    )
