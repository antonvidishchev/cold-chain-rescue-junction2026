import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';

// Run against the independently initialized five-clinic cloud fixture, not mocks.
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  const errors = [];
  const writes = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().includes('/api/') && request.method() !== 'GET') writes.push(request.url());
  });
  await page.goto(process.env.SMOKE_URL || 'http://localhost:5173', { waitUntil: 'networkidle' });
  await page.locator('.clinic-row').filter({ hasText: 'Helsinki' }).click();
  await page.getByRole('heading', { name: /Helsinki.*Fictional clinic/ }).waitFor();
  assert.equal(await page.locator('.clinic-row').count(), 5);
  assert.equal(await page.locator('.map-pin').count(), 5);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.clinic-row').filter({ hasText: 'Oulu' }).click();
  await page.getByRole('heading', { name: /Oulu.*Fictional clinic/ }).waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []);
  assert.deepEqual(writes, []);
  console.log('Edge smoke passed: five clinics/markers, linked selection, responsive layout, no runtime errors or API writes.');
} finally {
  await browser.close();
}
