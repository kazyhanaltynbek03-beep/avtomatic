"""Upgrade safety for the discount migration on an existing ledger."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _alembic(database, revision):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, result.stdout + "\\n" + result.stderr
    return result


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
            INSERT INTO returns (id, company_id, sale_id, date, reference, quantity, revenue, cogs, created_at)
              VALUES (1, 1, 1, '2026-01-02', 'OLD-RETURN', 1, 10000, 4000, '2026-01-02 00:00:00');
            """
        )
        connection.commit()
    finally:
        connection.close()

    _alembic(database, "b1c7d9e2a410")
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            INSERT INTO accounts (id, company_id, name, channel, mode, credential_ref, created_at)
              VALUES (2, 1, 'Kaspi', 'Kaspi', 'manual', '', '2026-01-01 00:00:00');
            INSERT INTO sales (id, company_id, account_id, product_id, reference, date, quantity, revenue, cogs, commission, logistics, advertising, created_at)
              VALUES (2, 1, 2, 1, 'KASPI-ORDER-2', '2026-01-03', 3, 30000, 0, 0, 0, 0, '2026-01-03 00:00:00');
            """
        )
        connection.commit()
    finally:
        connection.close()

    _alembic(database, "head")
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT reference, revenue, discount FROM sales WHERE id = 1").fetchone() == ("OLD-SALE", 10000, 0)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("d57c9e1a4b20",)
        assert connection.execute(
            "SELECT quantity, kind, batch_id, reference FROM movements WHERE reference = 'KASPI-ORDER-2'"
        ).fetchall() == [(-3, "sale_pending_fifo", None, "KASPI-ORDER-2")]
        assert connection.execute("SELECT active FROM accounts WHERE id = 1").fetchone() == (1,)
        assert connection.execute("SELECT integration_settings FROM accounts WHERE id = 1").fetchone() == ("{}",)
        assert connection.execute("SELECT inventory_status FROM returns WHERE id = 1").fetchone() == ("restocked",)
        connection.execute(
            "INSERT INTO returns (id, company_id, sale_id, date, reference, quantity, revenue, cogs, created_at) "
            "VALUES (2, 1, 1, '2026-01-03', 'NEW-RETURN', 1, 10000, 4000, '2026-01-03 00:00:00')"
        )
        assert connection.execute("SELECT inventory_status FROM returns WHERE id = 2").fetchone() == ("requested",)
    finally:
        connection.close()
