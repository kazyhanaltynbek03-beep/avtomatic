"""Exercise the release migration on an isolated PostgreSQL 18 CI database."""
import os
import subprocess
import sys
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.skipif(not os.getenv('QOR_POSTGRES_MIGRATION_URL'), reason='Dedicated PostgreSQL CI database required')
def test_postgres_upgrade_preserves_existing_ledger():
    url = os.environ['QOR_POSTGRES_MIGRATION_URL']
    parsed = urlsplit(url)
    assert parsed.hostname in {'localhost', '127.0.0.1'}
    assert parsed.path == '/qor_migration_test'
    env = {**os.environ, 'DATABASE_URL': url}

    def upgrade(revision):
        result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision],
                                env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr

    engine = create_engine(url)
    upgrade('c2f5a8d1e300')
    with engine.begin() as conn:
        statements = [
            "INSERT INTO companies (id,name,bin,kind,active,created_at) VALUES (1,'Existing','000000000001','LLP',true,now())",
            "INSERT INTO accounts (id,company_id,name,channel,mode,credential_ref,created_at) VALUES (1,1,'Existing','Offline','manual','',now())",
            "INSERT INTO products (id,sku,name,category,price,min_stock,active,specifications,created_at) VALUES (1,'OLD-1','Existing SKU','',0,0,true,'{}',now())",
            "INSERT INTO sales (id,company_id,account_id,product_id,reference,date,quantity,revenue,cogs,commission,logistics,advertising,created_at) VALUES (1,1,1,1,'OLD-SALE','2026-01-01',1,10000,4000,0,0,0,now())",
            "INSERT INTO returns (id,company_id,sale_id,date,reference,quantity,revenue,cogs,created_at) VALUES (1,1,1,'2026-01-02','OLD-RETURN',1,10000,4000,now())",
        ]
        for statement in statements:
            conn.execute(text(statement))
    upgrade('head')
    with engine.begin() as conn:
        assert conn.execute(text('SELECT reference,revenue FROM sales WHERE id=1')).one() == ('OLD-SALE',10000)
        assert conn.execute(text('SELECT inventory_status FROM returns WHERE id=1')).scalar_one() == 'restocked'
        assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == 'f98b9c1d2008'
        conn.execute(text("INSERT INTO returns (id,company_id,sale_id,date,reference,quantity,revenue,cogs,created_at) VALUES (2,1,1,'2026-01-03','NEW-RETURN',1,10000,4000,now())"))
        assert conn.execute(text('SELECT inventory_status FROM returns WHERE id=2')).scalar_one() == 'requested'
        assert conn.execute(text('SELECT count(*) FROM return_inventory_allocations')).scalar_one() == 0
    engine.dispose()
