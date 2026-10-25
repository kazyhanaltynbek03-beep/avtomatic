import os, tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="qor-tests-"), "test.db")
os.environ["COOKIE_SECURE"] = "false"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="qor-uploads-")
import pytest
from fastapi.testclient import TestClient
from app.db import Base, engine, SessionLocal
from app.models import User, Company, Product, Account, Customer, Setting
from app.security import passwords
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all(
            [
                Company(id=1, name="Test", bin="000000000001"),
                Company(id=2, name="Other", bin="000000000002"),
            ]
        )
        db.flush()
        db.add_all(
            [
                User(
                    id=1,
                    email="owner@test.kz",
                    name="Owner",
                    password_hash=passwords.hash("Test-password-1!"),
                    role="Owner",
                ),
                User(
                    id=2,
                    email="warehouse@test.kz",
                    name="Stock",
                    password_hash=passwords.hash("Test-password-1!"),
                    role="Warehouse",
                    company_ids=[1],
                ),
                User(
                    id=3,
                    email="marketing@test.kz",
                    name="Market",
                    password_hash=passwords.hash("Test-password-1!"),
                    role="Marketing",
                    company_ids=[1],
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                Product(id=1, sku="A", name="Alpha", price=10000),
                Product(id=2, sku="B", name="Beta"),
                Account(id=1, company_id=1, name="Kaspi", channel="Kaspi"),
                Account(id=2, company_id=2, name="Other", channel="Kaspi"),
                Account(id=3, company_id=1, name="B2B", channel="B2B"),
                Customer(id=1, company_id=1, name="Client"),
                Setting(id=1),
            ]
        )
        db.commit()
    with TestClient(app) as c:
        auth = c.post(
            "/api/auth/login",
            json={"email": "owner@test.kz", "password": "Test-password-1!"},
        ).json()
        c.headers["X-CSRF-Token"] = auth["csrf"]
        yield c


def post(c, entity, **kw):
    r = c.post("/api/post/" + entity, json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def buy(c, ref="P1", qty=10, cost=1000, extra=0, paid=0, day="2026-10-01", company=1):
    return post(
        c,
        "purchases",
        company_id=company,
        reference=ref,
        supplier="Supplier",
        date=day,
        extra_cost=extra,
        paid=paid,
        lines=[{"product_id": 1, "quantity": qty, "unit_cost": cost}],
    )


def sell(c, ref="S1", qty=3, price=3000, paid=0, account=1, day="2026-10-02", **kw):
    return post(
        c,
        "sales",
        company_id=1,
        account_id=account,
        product_id=1,
        reference=ref,
        date=day,
        quantity=qty,
        unit_price=price,
        paid=paid,
        **kw,
    )


def report(c, start="2026-10-01", end="2026-10-31"):
    r = c.get("/api/report", params={"start": start, "end": end})
    assert r.status_code == 200, r.text
    return r.json()
