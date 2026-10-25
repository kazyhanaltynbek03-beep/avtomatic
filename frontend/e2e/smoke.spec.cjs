const { expect, test } = require("@playwright/test");

test("owner can log in, open core pages and log out without browser errors", async ({ page }) => {
  const consoleErrors = [];
  const failedApi = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 500) failedApi.push(response.url());
  });

  await page.goto("/");
  await page.getByLabel("Email").fill("owner@qor-e2e.local");
  await page.getByLabel("Пароль").fill(process.env.QOR_E2E_PASSWORD);
  await page.getByRole("button", { name: "Войти в систему" }).click();
  await expect(page.getByRole("heading", { name: "Обзор бизнеса" })).toBeVisible();

  for (const pageName of ["Все продажи", "Прибыль", "Единый склад", "Интеграции", "Импорт / Экспорт"]) {
    await page.getByRole("button", { name: pageName, exact: true }).click();
    await expect(page.getByRole("heading", { name: pageName })).toBeVisible();
  }

  await page.getByRole("button", { name: "Business Assistant", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Business Assistant" })).toBeVisible();
  await page.getByTitle("Выйти").click();
  await expect(page.getByRole("heading", { name: "Добро пожаловать" })).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(failedApi).toEqual([]);
});
