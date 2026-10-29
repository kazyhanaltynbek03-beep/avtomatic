const { expect, test } = require("@playwright/test");

test("owner can log in, open core pages and log out without browser errors", async ({ page }) => {
  const consoleErrors = [];
  const failedApi = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401 (Unauthorized)")) consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("response", (response) => {
    const expectedAnonymousSessionCheck = response.url().endsWith("/api/auth/me") && response.status() === 401;
    if (response.url().includes("/api/") && response.status() >= 400 && !expectedAnonymousSessionCheck) failedApi.push(`${response.status()} ${response.url()}`);
  });

  await page.goto("/");
  await page.getByLabel("Email").fill("owner@qor-e2e.local");
  await page.getByLabel("Пароль").fill(process.env.QOR_E2E_PASSWORD);
  await page.getByRole("button", { name: "Войти в систему" }).click();
  await expect(page.getByRole("heading", { name: "Обзор бизнеса" })).toBeVisible();
  await expect(page.locator(".qor-marketplace-summary-card")).toHaveCount(3);
  await expect(page.getByRole("heading", { name: "Доля по маркетплейсам" })).toBeVisible();

  for (const pageName of ["Все продажи", "Прибыль", "Единый склад", "Интеграции", "Импорт / Экспорт"]) {
    await page.getByRole("button", { name: pageName, exact: true }).click();
    await expect(page.getByRole("heading", { name: pageName })).toBeVisible();
  }

  await page.getByRole("button", { name: /AI-ассистент/ }).click();
  await expect(page.getByRole("heading", { name: "AI-ассистент" })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Обзор", exact: true }).click();
  await expect(page.locator(".mobile-brand")).toBeVisible();
  const periodStyle = await page.locator(".toolbar > .periods").evaluate((element) => ({
    display: getComputedStyle(element).display,
    overflowX: getComputedStyle(element).overflowX,
  }));
  expect(periodStyle.display).toBe("flex");
  expect(["auto", "scroll"]).toContain(periodStyle.overflowX);
  await page.setViewportSize({ width: 1280, height: 900 });
  expect(consoleErrors, `API responses with errors: ${failedApi.join(", ")}`).toEqual([]);
  expect(failedApi).toEqual([]);
  await page.getByTitle("Выйти").click();
  await expect(page.getByRole("heading", { name: "Добро пожаловать" })).toBeVisible();
});
