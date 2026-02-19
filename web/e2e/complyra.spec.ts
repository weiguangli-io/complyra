import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const mockApi = async (page: Page) => {
  await page.route("**/api/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: "mock-token",
        token_type: "bearer",
        role: "admin",
        user_id: "u-1",
        default_tenant_id: "default"
      })
    });
  });

  await page.route("**/api/chat/", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "completed",
        answer: "Mocked governed answer",
        retrieved: [
          {
            text: "SOC2 policy sample",
            score: 0.98,
            source: "policy.md"
          }
        ],
        approval_id: null
      })
    });
  });

  await page.route("**/api/users/**", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            user_id: "u-1",
            username: "alice",
            role: "admin",
            default_tenant_id: "default",
            tenant_ids: ["default"],
            created_at: "2026-02-08T00:00:00Z"
          }
        ])
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true })
    });
  });

  await page.route("**/api/tenants/**", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            tenant_id: "default",
            name: "Default",
            created_at: "2026-02-08T00:00:00Z"
          }
        ])
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tenant_id: "new", name: "New" })
    });
  });

};

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("login + ask + admin flow works", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("login-button").click();
  await expect(page.getByTestId("login-button")).toBeDisabled();

  await page.getByTestId("question-input").fill("What controls are required?");
  await page.getByTestId("run-query-button").click();
  await expect(page.getByTestId("answer-content")).toContainText("Mocked governed answer");

  await page.getByTestId("tab-admin").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("admin-panel")).toBeVisible();

  await page.getByTestId("load-users-button").click();
  await expect(page.getByTestId("admin-users-list")).toContainText("alice");
});

test("a11y audit has no serious violations", async ({ page }) => {
  await page.goto("/");
  const results = await new AxeBuilder({ page }).analyze();

  const serious = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical"
  );

  expect(serious).toEqual([]);
});
