"""Backfill confirmed marketplace sale quantities into the stock ledger.

Revision ID: b2d8e3f4a501
Revises: b1c7d9e2a410
"""
from alembic import op


revision = "b2d8e3f4a501"
down_revision = "b1c7d9e2a410"
branch_labels = None
depends_on = None


def upgrade():
    # Earlier marketplace imports could confirm a sale without creating its
    # quantity movement when FIFO stock was missing. Reconcile only the gap:
    # existing allocated sale movements are subtracted, making this safe for
    # deployments where some sales were already posted.
    op.execute("""
        WITH confirmed AS (
            SELECT s.company_id, s.product_id, s.reference, s.date,
                   SUM(s.quantity) AS sold_quantity
            FROM sales AS s
            JOIN accounts AS a ON a.id = s.account_id
            WHERE a.channel IN ('Kaspi', 'Wildberries', 'Ozon')
            GROUP BY s.company_id, s.product_id, s.reference, s.date
        ), posted AS (
            SELECT m.company_id, m.product_id, m.reference, m.date,
                   SUM(CASE WHEN m.quantity < 0 THEN -m.quantity ELSE 0 END) AS posted_quantity
            FROM movements AS m
            WHERE m.kind IN ('sale', 'sale_pending_fifo')
            GROUP BY m.company_id, m.product_id, m.reference, m.date
        )
        INSERT INTO movements
            (company_id, product_id, batch_id, date, quantity, cost, kind, reference, created_at)
        SELECT c.company_id, c.product_id, NULL, c.date,
               -(c.sold_quantity - COALESCE(p.posted_quantity, 0)),
               0, 'sale_pending_fifo', c.reference, CURRENT_TIMESTAMP
        FROM confirmed AS c
        LEFT JOIN posted AS p
          ON p.company_id = c.company_id
         AND p.product_id = c.product_id
         AND p.reference = c.reference
         AND p.date = c.date
        WHERE c.sold_quantity > COALESCE(p.posted_quantity, 0)
    """)


def downgrade():
    # Backfilled rows are indistinguishable from valid pending-FIFO sale
    # movements and may already have been used by reports; do not delete them.
    pass
