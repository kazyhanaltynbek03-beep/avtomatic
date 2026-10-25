const { defineConfig } = require("@playwright/test");

const python = process.env.QOR_E2E_PYTHON || "python3";
const password = process.env.QOR_E2E_PASSWORD;

if (!password) throw new Error("Set QOR_E2E_PASSWORD before running browser E2E.");

module.exports = defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  forbidOnly: !!process.env.CI,
  use: { baseURL: "http://127.0.0.1:8000", trace: "retain-on-failure" },
  webServer: {
    command: [
      "rm -f /tmp/qor-e2e.db /tmp/qor-e2e.db-shm /tmp/qor-e2e.db-wal",
      "cd ../backend",
      `DATABASE_URL=sqlite:////tmp/qor-e2e.db OWNER_EMAIL=owner@qor-e2e.local OWNER_PASSWORD="$QOR_E2E_PASSWORD" COOKIE_SECURE=false ${python} -m alembic upgrade head`,
      `DATABASE_URL=sqlite:////tmp/qor-e2e.db OWNER_EMAIL=owner@qor-e2e.local OWNER_PASSWORD="$QOR_E2E_PASSWORD" COOKIE_SECURE=false ${python} -m app.seed --demo`,
      `DATABASE_URL=sqlite:////tmp/qor-e2e.db OWNER_EMAIL=owner@qor-e2e.local OWNER_PASSWORD="$QOR_E2E_PASSWORD" COOKIE_SECURE=false FRONTEND_DIST=../frontend/dist ${python} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
    ].join(" && "),
    port: 8000,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
