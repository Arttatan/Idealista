import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const NOTES = path.join(ROOT, "data", "user_notes.json");
const GITHUB = "https://arttatan.github.io/Idealista/";
const NOTE_ID = "35464805";

async function ready(page) {
  await page.goto("/");
  await expect(page.locator("#count")).toContainText("120 квартир");
}

test("вход не нужен локально, список из 120 карточек", async ({ page }) => {
  await ready(page);
  await expect(page.locator("#lock")).toHaveClass(/hidden/);
  await expect(page.locator("#list .card")).toHaveCount(120);
  await expect(page.locator("body")).not.toContainText("NaN");
  await expect(page.locator("body")).not.toContainText("undefined");
});

test("фильтр города и пустой результат", async ({ page }) => {
  await ready(page);
  await page.locator("#f-city-summary").click();
  await page.locator('#f-city input[value="Porto"]').check();
  await expect(page.locator("#count")).toHaveText("3 из 120 квартир");
  await expect(page.locator("#list .card")).toHaveCount(3);

  await page.locator("#f-reset").click();
  await page.locator("#f-min").fill("9999999");
  await expect(page.locator("#count")).toHaveText("0 из 120 квартир");
  await expect(page.locator("#empty")).toBeVisible();
  await expect(page.locator("#empty")).toContainText("Ничего не нашлось");
});

test("сортировка по цене: избранные выше, дальше по возрастанию", async ({ page }) => {
  await ready(page);
  await page.locator("#sort").selectOption("price");
  await expect(page.locator("#sort-dir")).toHaveAttribute("aria-label", "По возрастанию");
  const ok = await page.evaluate(() => {
    const items = filtered();
    for (let i = 1; i < items.length; i += 1) {
      const a = items[i - 1];
      const b = items[i];
      const aFav = Boolean(a.notes && a.notes["Избранное"]);
      const bFav = Boolean(b.notes && b.notes["Избранное"]);
      if (aFav !== bFav) {
        if (!aFav && bFav) return false;
        continue;
      }
      const aNew = isNew(a);
      const bNew = isNew(b);
      if (aNew !== bNew) {
        if (!aNew && bNew) return false;
        continue;
      }
      if (a.price > b.price) return false;
    }
    return items.length === 120 && state.dir === "asc";
  });
  expect(ok).toBe(true);
});

test("заметка сохраняется после перезагрузки и затем стирается", async ({ page }) => {
  const original = fs.readFileSync(NOTES);
  try {
    await ready(page);
    await page.locator(`.card[data-id="${NOTE_ID}"]`).click();
    const field = page.locator('#panel textarea[name="Заметки"]');
    await field.fill("QA-PW-TEMP");
    await expect(page.locator("#save-state")).toHaveText("Сохранено");
    await page.reload();
    await expect(page.locator("#count")).toContainText("120 квартир");
    const note = await page.evaluate((id) => {
      const item = state.all.find((row) => row.id === id);
      return item && item.notes["Заметки"];
    }, NOTE_ID);
    expect(note).toBe("QA-PW-TEMP");
  } finally {
    fs.writeFileSync(NOTES, original);
  }
});

test("экспорт Excel скачивается", async ({ request }) => {
  const response = await request.get("/api/export.xlsx");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"] || "").toContain("spreadsheetml");
  const body = await response.body();
  expect(body.subarray(0, 2).toString()).toBe("PK");
  expect(body.length).toBeGreaterThan(10_000);
});

test("ставка Maia находится по имени города, метро без станции — прочерк", async ({ page }) => {
  await ready(page);
  const rents = await page.evaluate(() => ({
    maia: state.all.find((row) => row.id === "35478425").rent.rent,
    known: state.all.find((row) => row.id === "35464805").rent.rent,
    empty: state.all.find((row) => row.id === "35476670").rent.rent,
  }));
  expect(rents.maia).toBe(910);
  expect(rents.known).toBe(1120);
  expect(rents.empty).toBeNull();

  await page.getByRole("button", { name: "Таблица" }).click();
  const row = page.locator("tr", { has: page.locator('a[href*="35476870"]') });
  await expect(row.locator('td[data-label="Метро"]')).toHaveText("—");
});

test("карта рисует все точки", async ({ page }) => {
  await ready(page);
  await page.getByRole("button", { name: "Карта" }).click();
  await expect(page.locator("#map.leaflet-container")).toBeVisible();
  await expect(page.locator("#map-error")).toBeHidden();
  await expect.poll(async () => page.evaluate(() => (
    state.cluster ? state.cluster.getLayers().length : 0
  ))).toBe(120);
});

test("GitHub Pages: неверный пароль", async ({ page }) => {
  await page.goto(GITHUB);
  await page.locator("#lock-pass").fill("wrong-password-qa");
  await page.locator('#lock-form button[type="submit"]').click();
  await expect(page.locator("#lock-error")).toContainText("Пароль не подошёл");
  await expect(page.locator("#lock")).not.toHaveClass(/hidden/);
});

test("GitHub Pages: верный пароль открывает тот же список", async ({ page }) => {
  test.skip(!process.env.IDEALISTA_PASSWORD, "Нет IDEALISTA_PASSWORD");
  await page.goto(GITHUB);
  await page.locator("#lock-pass").fill(process.env.IDEALISTA_PASSWORD);
  await page.locator('#lock-form button[type="submit"]').click();
  await expect(page.locator("#count")).toContainText("120 квартир");
  await expect(page.locator("#lock")).toHaveClass(/hidden/);
  await expect(page.locator("#export")).toHaveClass(/hidden/);
  await expect(page.locator("#list .card")).toHaveCount(120);
});
