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
  const checklistWrites = [];
  let actingOnChecklist = false;
  let incident = { id: 101, location_id: 'fridge-a', type: 'POWER_LOSS', message: 'Fixture incident', status: 'open',
    created_at: new Date().toISOString(), recovered_at: null, protocol: null,
    checklist: ['inspect', 'protect', 'verify'].map(id => ({ id, label: `Legacy ${id}`, done: false })),
  };
  const publicChecklistPath = /^\/api\/alerts\/101\/public-checklist\/(inspect|protect|verify)$/;
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().includes('/api/') && request.method() !== 'GET') {
      if (actingOnChecklist && request.method() === 'PATCH' && publicChecklistPath.test(new URL(request.url()).pathname)) checklistWrites.push(request);
      else writes.push(request.url());
    }
  });
  if (process.env.SMOKE_FIXTURES === '1') await page.route('**/api/**', route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'PATCH' && actingOnChecklist && publicChecklistPath.test(path)) {
      const id = path.split('/').at(-1);
      assert.deepEqual(request.postDataJSON(), { done: true });
      incident = { ...incident, checklist: incident.checklist.map(item => item.id === id ? { ...item, done: true } : item) };
      if (incident.checklist.every(item => item.done)) incident = { ...incident, status: 'resolved_by_user', user_resolved_at: new Date().toISOString(), resolution_source: 'public_checklist' };
      return route.fulfill({ json: incident });
    }
    if (request.method() !== 'GET') return route.abort();
    return route.fulfill({ json: path.endsWith('/clinics') ? fixtures : path.endsWith('/alerts') ? [incident] : [] });
  });
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
  if (process.env.SMOKE_FIXTURES === '1') {
    actingOnChecklist = true;
    for (const label of ['Unit is inspected', 'Incident acted upon. Stock transferred to another unit or location', 'Recovery verified']) {
      const checkbox = page.getByRole('checkbox', { name: label, exact: true });
      const [response] = await Promise.all([
        page.waitForResponse(response => response.request().method() === 'PATCH' && publicChecklistPath.test(new URL(response.url()).pathname)),
        checkbox.click(),
      ]);
      assert.equal(response.ok(), true);
      await page.waitForFunction(name => [...document.querySelectorAll('.checklist input')].some(input => input.getAttribute('aria-label') === name && input.checked), label);
      assert.equal(await checkbox.isChecked(), true);
    }
    await page.getByText('Resolved by user', { exact: true }).waitFor();
    assert.equal(await page.locator('.checklist input:not(:disabled)').count(), 0);
    assert.equal(await page.getByText(/Recovery observed/).count(), 0);
    assert.equal(checklistWrites.length, 3);
    actingOnChecklist = false;
    await page.getByRole('button', { name: /Refresh now/ }).click();
    await page.getByText('Resolved by user', { exact: true }).waitFor();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const site of catalogue.clinics) {
    const row = page.locator('.clinic-row').filter({ hasText: site.name });
    await row.focus();
    await page.keyboard.press('Enter');
    await page.locator('h2#clinic-detail').filter({ hasText: site.name }).waitFor();
    assert.match(await row.innerText(), /Not monitored \/ estimated capacity/);
    assert.doesNotMatch(await row.innerText(), /Offline|Awaiting device|No active incident|°C reading/);
    assert.equal(await page.locator('.temperature-panel').count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  }
  if (process.env.SMOKE_FIXTURES === '1') {
    await page.unroute('**/api/**');
    await page.route('**/api/**', route => route.request().method() === 'GET' ? route.fulfill({ json: route.request().url().split('?')[0].endsWith('/clinics') ? fixtures.map(site => ({ ...site, lat: null, lon: null })) : [] }) : route.abort());
    await page.getByRole('button', { name: /Refresh now/ }).click();
    await page.getByText(/No fallback locations are shown/).waitFor();
    assert.equal(await page.locator('.map-pin').count(), 0);
    assert.equal(await page.locator('.clinic-row').count(), fixtures.length);
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(writes, []);
  console.log('Edge smoke passed: catalogue sites/markers, neutral destinations, preserved zoom, keyboard mobile selection, no coordinate fallback, public checklist persistence, no runtime errors or unauthorized API writes.');
} finally {
  await browser.close();
}
