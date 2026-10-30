import { expect, test } from "@playwright/test";

const TOKEN = process.env.SENDGRID_INBOUND_TOKEN ?? "dev-sendgrid-token";
const INBOUND = process.env.E2E_INBOUND_EMAIL ?? "leasing-1-1@inbound.leaseloop.dev";

function nextWeekday(weeksAhead = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + 7 * weeksAhead);
  do d.setDate(d.getDate() + 1); while (d.getDay() === 0 || d.getDay() === 6);
  return d.toISOString().slice(0, 10);
}

/** A tour slot unlikely to collide with earlier runs against the same database. */
function tourSlot(run: number): string {
  const slot = run % 16; // 9:00 .. 16:30
  const time = `${String(9 + Math.floor(slot / 2)).padStart(2, "0")}:${slot % 2 ? "30" : "00"}`;
  return `${nextWeekday(1 + (Math.floor(run / 16) % 40))}T${time}`;
}

test("lead arrives by email webhook and ends with a signed lease", async ({ page, request }) => {
  const run = Date.now();
  const email = `e2e.${run}@example.com`;
  const name = `Morgan E2E${run % 100000}`;
  const body = "Hi! Is a 1 bedroom available next month? I'd love to see it.";
  const payload = {
    headers: `Message-ID: <e2e-${run}@mail.example.com>\nSubject: Apartment inquiry`,
    to: INBOUND,
    from: `${name} <${email}>`,
    subject: "Apartment inquiry",
    text: body,
    envelope: JSON.stringify({ to: [INBOUND], from: email }),
  };

  // 1. Lead arrives as a SendGrid Inbound Parse webhook; a redelivery is deduplicated.
  const url = `/api/webhooks/sendgrid/inbound/?token=${TOKEN}`;
  const first = await request.post(url, { multipart: payload });
  expect(first.ok()).toBeTruthy();
  expect((await first.json()).status).toBe("accepted");
  const retry = await request.post(url, { multipart: payload });
  expect((await retry.json()).status).toBe("duplicate");

  // 2. The agent sees it in the unified inbox.
  await page.goto("/login");
  await page.getByLabel("Email").fill("manager@org1.demo");
  await page.getByLabel("Password").fill("demo1234!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/inbox$/);
  const row = page.getByRole("button", { name: new RegExp(name) });
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.getByLabel("Messages").getByText(body)).toBeVisible();

  // 3. Open the new prospect and book a tour.
  await page.getByRole("link", { name: "Prospects" }).click();
  await page.getByLabel("Search prospects").fill(email);
  await page.getByLabel("Search prospects").press("Enter");
  await page.getByRole("link", { name }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByLabel("Pipeline status")).toHaveValue("NEW");

  const unitSelect = page.getByLabel("Unit", { exact: true });
  await expect(unitSelect.locator("option")).not.toHaveCount(1);
  const unitValue = await unitSelect.locator("option").nth(1).getAttribute("value");
  await unitSelect.selectOption(unitValue!);
  await page.getByLabel("Tour time").fill(tourSlot(run));
  await page.getByRole("button", { name: "Schedule tour" }).click();
  await expect(page.getByLabel("Pipeline status")).toHaveValue("TOUR_SCHEDULED");
  await expect(page.getByRole("region", { name: "Tours" }).getByRole("listitem")).toHaveCount(1);

  // 4. Application: start, submit, approve.
  await page.getByRole("button", { name: "Start application" }).click();
  await page.getByRole("button", { name: "Submit application" }).click();
  await expect(page.getByLabel("Pipeline status")).toHaveValue("APPLIED");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByLabel("Pipeline status")).toHaveValue("APPROVED");

  // 5. Lease: create and sign.
  await page.getByLabel("Lease start").fill(nextWeekday());
  await page.getByRole("button", { name: "Create lease" }).click();
  await page.getByRole("button", { name: "Mark lease signed" }).click();
  await expect(page.getByText("signed", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Pipeline status")).toHaveValue("LEASED");

  // The unit is no longer offered for tours or applications.
  await expect(unitSelect.locator(`option[value="${unitValue}"]`)).toHaveCount(0);
});
