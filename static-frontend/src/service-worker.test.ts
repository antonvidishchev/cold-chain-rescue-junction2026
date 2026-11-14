import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { expect, it, vi } from 'vitest';
it('renders only notification text and rejects external notification click URLs', async () => {
  const handlers: Record<string, (event: Record<string, unknown>) => void> = {};
  const showNotification = vi.fn().mockResolvedValue(undefined);
  const openWindow = vi.fn().mockResolvedValue(undefined);
  const self = { location: { origin: 'https://demo.example' }, addEventListener: (name: string, fn: typeof handlers[string]) => { handlers[name] = fn; }, registration: { showNotification }, clients: { matchAll: vi.fn().mockResolvedValue([]), openWindow } };
  vm.runInNewContext(readFileSync('public\\sw.js', 'utf8'), { self, URL });
  let promise: Promise<unknown> | undefined;
  const waitUntil = (value: Promise<unknown>) => { promise = value; };
  handlers.push({ data: { json: () => ({ id: '1', message: '<b>not HTML</b>', location_id: 'fridge-a', url: 'https://evil.example' }) }, waitUntil });
  await promise;
  expect(showNotification).toHaveBeenCalledWith('Cold Chain · fictional demo', expect.objectContaining({ body: '<b>not HTML</b>', data: { url: 'https://demo.example/?clinic=fridge-a#incidents' } }));
  handlers.notificationclick({ notification: { close: vi.fn(), data: { url: 'https://evil.example/' } }, waitUntil });
  await promise;
  expect(openWindow).toHaveBeenCalledWith('https://demo.example/');
});
