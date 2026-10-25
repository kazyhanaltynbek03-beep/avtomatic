BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> fa66e2f700f0

CREATE TABLE companies (
    name VARCHAR(160) NOT NULL, 
    bin VARCHAR(12) NOT NULL, 
    kind VARCHAR(20) NOT NULL, 
    active BOOLEAN NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (bin)
);

CREATE TABLE login_attempts (
    identity VARCHAR(64) NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_login_attempts_identity ON login_attempts (identity);

CREATE TABLE niches (
    name VARCHAR(150) NOT NULL, 
    source TEXT NOT NULL, 
    observed_at DATE NOT NULL, 
    data JSON NOT NULL, 
    method TEXT NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE products (
    sku VARCHAR(100) NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    category VARCHAR(100) NOT NULL, 
    price BIGINT NOT NULL, 
    min_stock INTEGER NOT NULL, 
    active BOOLEAN NOT NULL, 
    specifications JSON NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (price >= 0 AND min_stock >= 0), 
    UNIQUE (sku)
);

CREATE TABLE settings (
    id SERIAL NOT NULL, 
    business_name VARCHAR(160) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    timezone VARCHAR(60) NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE users (
    email VARCHAR(200) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    password_hash TEXT NOT NULL, 
    role VARCHAR(20) NOT NULL, 
    company_ids JSON NOT NULL, 
    active BOOLEAN NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (email)
);

CREATE TABLE accounts (
    company_id INTEGER NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    channel VARCHAR(20) NOT NULL, 
    mode VARCHAR(20) NOT NULL, 
    credential_ref VARCHAR(100) NOT NULL, 
    last_sync TIMESTAMP WITH TIME ZONE, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id)
);

CREATE TABLE audit (
    user_id INTEGER, 
    action VARCHAR(80) NOT NULL, 
    entity VARCHAR(80) NOT NULL, 
    entity_id INTEGER, 
    details JSON NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE customers (
    company_id INTEGER NOT NULL, 
    name VARCHAR(160) NOT NULL, 
    phone VARCHAR(40) NOT NULL, 
    bin VARCHAR(12) NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id)
);

CREATE TABLE documents (
    company_id INTEGER NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    kind VARCHAR(40) NOT NULL, 
    path VARCHAR(250) NOT NULL, 
    mime VARCHAR(100) NOT NULL, 
    size INTEGER NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id)
);

CREATE TABLE imports (
    user_id INTEGER NOT NULL, 
    kind VARCHAR(40) NOT NULL, 
    fingerprint VARCHAR(64) NOT NULL, 
    mapping JSON NOT NULL, 
    rows JSON NOT NULL, 
    errors JSON NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE jobs (
    company_id INTEGER, 
    user_id INTEGER NOT NULL, 
    kind VARCHAR(40) NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    payload JSON NOT NULL, 
    result JSON NOT NULL, 
    attempts INTEGER NOT NULL, 
    error TEXT NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE purchases (
    company_id INTEGER NOT NULL, 
    reference VARCHAR(100) NOT NULL, 
    supplier VARCHAR(160) NOT NULL, 
    date DATE NOT NULL, 
    total BIGINT NOT NULL, 
    extra_cost BIGINT NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id), 
    UNIQUE (reference)
);

CREATE TABLE sessions (
    token_hash VARCHAR(64) NOT NULL, 
    user_id INTEGER NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (token_hash)
);

CREATE TABLE batches (
    company_id INTEGER NOT NULL, 
    product_id INTEGER NOT NULL, 
    purchase_id INTEGER, 
    date DATE NOT NULL, 
    quantity INTEGER NOT NULL, 
    remaining INTEGER NOT NULL, 
    total_cost BIGINT NOT NULL, 
    remaining_cost BIGINT NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (quantity > 0 AND remaining >= 0 AND remaining <= quantity AND total_cost >= 0 AND remaining_cost >= 0), 
    FOREIGN KEY(company_id) REFERENCES companies (id), 
    FOREIGN KEY(product_id) REFERENCES products (id), 
    FOREIGN KEY(purchase_id) REFERENCES purchases (id)
);

CREATE TABLE expenses (
    company_id INTEGER NOT NULL, 
    account_id INTEGER, 
    reference VARCHAR(120) NOT NULL, 
    date DATE NOT NULL, 
    category VARCHAR(80) NOT NULL, 
    description TEXT NOT NULL, 
    amount BIGINT NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (amount > 0), 
    FOREIGN KEY(account_id) REFERENCES accounts (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id), 
    UNIQUE (reference)
);

CREATE TABLE sales (
    company_id INTEGER NOT NULL, 
    account_id INTEGER NOT NULL, 
    customer_id INTEGER, 
    product_id INTEGER NOT NULL, 
    reference VARCHAR(120) NOT NULL, 
    date DATE NOT NULL, 
    due_date DATE, 
    quantity INTEGER NOT NULL, 
    revenue BIGINT NOT NULL, 
    cogs BIGINT NOT NULL, 
    commission BIGINT NOT NULL, 
    logistics BIGINT NOT NULL, 
    advertising BIGINT NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (quantity > 0 AND revenue >= 0 AND cogs >= 0 AND commission >= 0 AND logistics >= 0 AND advertising >= 0), 
    FOREIGN KEY(account_id) REFERENCES accounts (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id), 
    FOREIGN KEY(customer_id) REFERENCES customers (id), 
    FOREIGN KEY(product_id) REFERENCES products (id), 
    UNIQUE (reference)
);

CREATE TABLE allocations (
    sale_id INTEGER NOT NULL, 
    batch_id INTEGER NOT NULL, 
    quantity INTEGER NOT NULL, 
    cost BIGINT NOT NULL, 
    returned INTEGER NOT NULL, 
    returned_cost BIGINT NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(batch_id) REFERENCES batches (id), 
    FOREIGN KEY(sale_id) REFERENCES sales (id)
);

CREATE TABLE cash (
    company_id INTEGER NOT NULL, 
    sale_id INTEGER, 
    purchase_id INTEGER, 
    expense_id INTEGER, 
    reference VARCHAR(140) NOT NULL, 
    date DATE NOT NULL, 
    amount BIGINT NOT NULL, 
    category VARCHAR(60) NOT NULL, 
    description TEXT NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id), 
    FOREIGN KEY(expense_id) REFERENCES expenses (id), 
    FOREIGN KEY(purchase_id) REFERENCES purchases (id), 
    FOREIGN KEY(sale_id) REFERENCES sales (id), 
    UNIQUE (reference)
);

CREATE TABLE movements (
    company_id INTEGER NOT NULL, 
    product_id INTEGER NOT NULL, 
    batch_id INTEGER NOT NULL, 
    date DATE NOT NULL, 
    quantity INTEGER NOT NULL, 
    cost BIGINT NOT NULL, 
    kind VARCHAR(30) NOT NULL, 
    reference VARCHAR(160) NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(batch_id) REFERENCES batches (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id), 
    FOREIGN KEY(product_id) REFERENCES products (id)
);

CREATE TABLE returns (
    company_id INTEGER NOT NULL, 
    sale_id INTEGER NOT NULL, 
    date DATE NOT NULL, 
    reference VARCHAR(120) NOT NULL, 
    quantity INTEGER NOT NULL, 
    revenue BIGINT NOT NULL, 
    cogs BIGINT NOT NULL, 
    id SERIAL NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id), 
    FOREIGN KEY(sale_id) REFERENCES sales (id), 
    UNIQUE (reference)
);

INSERT INTO alembic_version (version_num) VALUES ('fa66e2f700f0') RETURNING alembic_version.version_num;

-- Running upgrade fa66e2f700f0 -> 90dae75ab0be

CREATE INDEX ix_allocations_sale ON allocations (sale_id);

CREATE INDEX ix_audit_created ON audit (created_at);

CREATE INDEX ix_batches_company_date ON batches (company_id, date);

CREATE INDEX ix_batches_fifo ON batches (company_id, product_id, date);

CREATE INDEX ix_cash_company_date ON cash (company_id, date);

CREATE INDEX ix_cash_sale ON cash (sale_id);

CREATE INDEX ix_expenses_company_date ON expenses (company_id, date);

CREATE INDEX ix_imports_fingerprint_status ON imports (fingerprint, status);

CREATE INDEX ix_jobs_queue ON jobs (status, id);

CREATE INDEX ix_movements_company_date ON movements (company_id, date);

CREATE INDEX ix_purchases_company_date ON purchases (company_id, date);

CREATE INDEX ix_returns_company_date ON returns (company_id, date);

CREATE INDEX ix_returns_sale ON returns (sale_id);

CREATE INDEX ix_sales_account_date ON sales (account_id, date);

CREATE INDEX ix_sales_company_date ON sales (company_id, date);

UPDATE alembic_version SET version_num='90dae75ab0be' WHERE alembic_version.version_num = 'fa66e2f700f0';

COMMIT;

