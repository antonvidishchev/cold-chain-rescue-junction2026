import { chromium } from '@playwright/test';
import assert from 'node:assert/strict';

// SMOKE_FIXTURES=1 uses the unchanged device catalogue as a deterministic API fixture.
import { readFileSync } from 'node:fs';
const catalogue = JSON.parse(readFileSync(new URL('../device/coldchain-watchdog/python/data/clinics.json', import.meta.url), 'utf8'));
const fixtures = [catalogue.main, ...catalogue.clinics].map((site, index) => ({ ...site,
  id: index === 0 ? 'fridge-a' : site.id, clinic_id: site.id, city: site.city || 'Espoo',
  synthetic: true, active: true, monitored: index === 0, devices: [],
  last_temp_c: null, last_reading_at: null, alarm_state: 'NORMAL', power_on: true,
  capacity_units: site.cold_storage_capacity_units ?? 100, used_units: 0,
  free_units: site.cold_storage_capacity_units ?? 100, effective_range: { min_c: 2, max_c: 8 },
}));
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  const errors = [];
  const writes = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().includes('/api/') && request.method() !== 'GET') writes.push(request.url());
  });
  if (process.env.SMOKE_FIXTURES === '1') await page.route('**/api/**', route => route.fulfill({ json: route.request().url().split('?')[0].endsWith('/clinics') ? fixtures : [] }));
  await page.goto(process.env.SMOKE_URL || 'http://localhost:5173', { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: /Espoonlahti Clinic.*Main monitored site/ }).waitFor();
  assert.equal(await page.locator('.clinic-row').count(), fixtures.length);
  assert.equal(await page.locator('.map-pin').count(), fixtures.length);
  assert.equal(await page.locator('.map-pin.destination').count(), catalogue.clinics.length);
  await page.getByRole('button', { name: 'Zoom in' }).click();
  const zoomedPositions = await page.locator('.leaflet-marker-icon').evaluateAll(markers => markers.map(marker => marker.style.transform));
  await page.getByRole('button', { name: /Refresh now/ }).click();
  await page.waitForTimeout(500);
  assert.deepEqual(await page.locator('.leaflet-marker-icon').evaluateAll(markers => markers.map(marker => marker.style.transform)), zoomedPositions);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const site of catalogue.clinics) {
    const row = page.locator('.clinic-row').filter({ hasText: site.name });
    await row.focus();
    await page.keyboard.press('Enter');
    await page.locator('h2#clinic-detail').filter({ hasText: site.name }).waitFor();
    assert.match(await row.innerText(), /Not monitored \/ demo capacity/);
    assert.doesNotMatch(await row.innerText(), /Offline|Awaiting device|No active incident|°C reading/);
    assert.equal(await page.locator('.temperature-panel').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  }
  if (process.env.SMOKE_FIXTURES === '1') {
    await page.unroute('**/api/**');
    await page.route('**/api/**', route => route.fulfill({ json: route.request().url().split('?')[0].endsWith('/clinics') ? fixtures.map(site => ({ ...site, lat: null, lon: null })) : [] }));
    await page.getByRole('button', { name: /Refresh now/ }).click();
    await page.getByText(/No fallback locations are shown/).waitFor();
    assert.equal(await page.locator('.map-pin').count(), 0);
    assert.equal(await page.locator('.clinic-row').count(), fixtures.length);
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(writes, []);
  console.log('Edge smoke passed: catalogue sites/markers, neutral destinations, preserved zoom, keyboard mobile selection, no coordinate fallback, no runtime errors or API writes.');
} finally {
  await browser.close();
}
