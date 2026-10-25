"""Upgrade safety for the discount migration on an existing ledger."""

import os
import sqlite3
import subprocess
import sys


def _alembic(database, revision):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_existing_database_upgrade_preserves_sales_and_defaults_discount(tmp_path):
    database = tmp_path / "existing-ledger.db"
    _alembic(database, "d15e0a1b2c3d")
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            INSERT INTO companies (id, name, bin, kind, active, created_at)
              VALUES (1, 'Existing', '000000000001', 'LLP', 1, '2026-01-01 00:00:00');
            INSERT INTO accounts (id, company_id, name, channel, mode, credential_ref, created_at)
              VALUES (1, 1, 'Offline', 'Offline', 'manual', '', '2026-01-01 00:00:00');
            INSERT INTO products (id, sku, name, category, price, min_stock, active, specifications, created_at)
              VALUES (1, 'OLD-1', 'Existing SKU', '', 0, 0, 1, '{}', '2026-01-01 00:00:00');
            INSERT INTO sales (id, company_id, account_id, product_id, reference, date, quantity, revenue, cogs, commission, logistics, advertising, created_at)
              VALUES (1, 1, 1, 1, 'OLD-SALE', '2026-01-01', 1, 10000, 4000, 0, 0, 0, '2026-01-01 00:00:00');
            """
        )
        connection.commit()
    finally:
        connection.close()

    _alembic(database, "head")
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT reference, revenue, discount FROM sales WHERE id = 1").fetchone() == ("OLD-SALE", 10000, 0)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("c2f5a8d1e300",)
        assert connection.execute("SELECT active FROM accounts WHERE id = 1").fetchone() == (1,)
    finally:
        connection.close()
