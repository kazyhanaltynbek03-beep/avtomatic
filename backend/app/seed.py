"""Idempotent bootstrap. Demo only on explicit --demo; never runs automatically."""

import os, sys, random
from datetime import date, timedelta
from sqlalchemy import select
from .db import SessionLocal
from .models import *
from .security import passwords
from . import schemas as s, finance as f


def seed(demo=False):
    password = os.getenv("OWNER_PASSWORD", "Qor-Demo-2026!" if demo else "")
    if len(password) < 12:
        raise SystemExit("Set OWNER_PASSWORD (at least 12 characters)")
    email = os.getenv("OWNER_EMAIL", "owner@qor.local")
    with SessionLocal() as db:
        # Keep the configured owner credentials in sync on every deployment.
        # This makes Render Environment the single source of truth for login.
        owner = db.scalar(select(User).where(User.email == email.lower()))
        if owner:
            owner.password_hash = passwords.hash(password)
            owner.role = "Owner"
            owner.active = True
            db.commit()
            print(f"Owner credentials synchronized: {email.lower()}")
            return

        # Do not overwrite an unrelated existing installation.
        if db.scalar(select(User.id).limit(1)):
            print("Existing installation has users but configured OWNER_EMAIL was not found; seed skipped")
            return

        owner = User(
            email=email.lower(),
            name="Алтынбек",
            password_hash=passwords.hash(password),
            role="Owner",
            company_ids=[],
        )
        db.add(owner)
        db.add(Setting(id=1, business_name="QOR Business"))
        db.flush()
        if not demo:
            db.commit()
            print("Owner created")
            return
        cs = [
            Company(name="Golden King Market", bin="260100000000", kind="ИП"),
            Company(name="QOR Trade", bin="260100000001", kind="ТОО"),
        ]
        db.add_all(cs)
        db.flush()
        products = [
            Product(sku=sku, name=name, category=cat, price=price * 100, min_stock=low)
            for sku, name, cat, price, low in [
                ("PRJ-01", "Мини-проектор Vision", "Электроника", 39900, 15),
                ("CHG-02", "Зарядная станция 3 в 1", "Аксессуары", 14900, 20),
                ("LMP-03", "Настольная лампа Aura", "Для дома", 18900, 10),
                ("BAG-04", "Рюкзак Urban 24", "Аксессуары", 22900, 12),
                ("BOT-05", "Термобутылка 750 мл", "Для дома", 7900, 25),
                ("EAR-06", "Наушники Air Sound", "Электроника", 24900, 15),
                ("CLK-07", "Часы настольные LED", "Для дома", 9900, 8),
            ]
        ]
        db.add_all(products)
        db.flush()
        accounts = []
        for c in cs:
            for channel in ["Kaspi", "Wildberries", "Ozon", "Offline", "B2B"]:
                a = Account(
                    company_id=c.id,
                    name=channel + (" · Основной" if c == cs[0] else " · Trade"),
                    channel=channel,
                    mode="csv",
                )
                db.add(a)
                accounts.append(a)
        db.flush()
        customers = []
        for c in cs:
            customer = Customer(
                company_id=c.id,
                name="ТОО Demo Retail",
                bin="260100000002",
                phone="+7 700 000 0000",
            )
            db.add(customer)
            customers.append(customer)
        db.flush()
        start = business_today() - timedelta(days=40)
        for ci, c in enumerate(cs):
            f.payment(
                db,
                owner,
                s.CashIn(
                    company_id=c.id,
                    reference=f"OPEN-{ci}",
                    date=start,
                    amount=8_000_000 * 100,
                    category="Вклад собственника",
                ),
            )
            f.purchase(
                db,
                owner,
                s.PurchaseIn(
                    company_id=c.id,
                    reference=f"PO-{ci}-001",
                    supplier="Demo Supply",
                    date=start,
                    extra_cost=42000 * 100,
                    paid=2_000_000 * 100,
                    lines=[
                        s.PurchaseLine(
                            product_id=p.id, quantity=120, unit_cost=int(p.price * 0.43)
                        )
                        for p in products
                    ],
                ),
            )
            f.purchase(
                db,
                owner,
                s.PurchaseIn(
                    company_id=c.id,
                    reference=f"PO-{ci}-002",
                    supplier="Demo Supply",
                    date=start + timedelta(days=1),
                    extra_cost=17000 * 100,
                    paid=0,
                    lines=[
                        s.PurchaseLine(
                            product_id=p.id, quantity=35, unit_cost=int(p.price * 0.48)
                        )
                        for p in products[:3]
                    ],
                ),
            )
        rng = random.Random(42)
        for day in range(3, 41):
            d = start + timedelta(days=day)
            for ci, c in enumerate(cs):
                for n in range(3 if ci == 0 else 1):
                    p = products[rng.randrange(6)]
                    a = accounts[ci * 5 + rng.randrange(5)]
                    qty = rng.randrange(1, 5)
                    f.sale(
                        db,
                        owner,
                        s.SaleIn(
                            company_id=c.id,
                            account_id=a.id,
                            customer_id=customers[ci].id
                            if a.channel == "B2B"
                            else None,
                            product_id=p.id,
                            reference=f"SO-{ci}-{day}-{n}",
                            date=d,
                            due_date=d + timedelta(days=14)
                            if a.channel == "B2B"
                            else None,
                            quantity=qty,
                            unit_price=p.price,
                            commission=int(p.price * qty * 0.09)
                            if a.channel in ("Kaspi", "Ozon", "Wildberries")
                            else 0,
                            logistics=900 * 100,
                            advertising=500 * 100,
                            paid=p.price * qty if a.channel != "B2B" else p.price,
                        ),
                    )
                if day % 10 == 0:
                    f.expense(
                        db,
                        owner,
                        s.ExpenseIn(
                            company_id=c.id,
                            reference=f"EXP-{ci}-{day}",
                            date=d,
                            category="Аренда" if day == 10 else "Реклама",
                            description="Демонстрационный расход",
                            amount=35000 * 100,
                            paid=True,
                        ),
                    )
        for c in cs:
            db.add(
                User(
                    email="warehouse" + str(c.id) + "@qor.local",
                    name="Склад · Demo",
                    password_hash=passwords.hash(password),
                    role="Warehouse",
                    company_ids=[c.id],
                )
            )
        db.commit()
        print("Demo seeded: owner@qor.local / Qor-Demo-2026!")


if __name__ == "__main__":
    seed("--demo" in sys.argv)
