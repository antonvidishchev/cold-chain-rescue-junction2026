/* Public notification delivery only. No API or map tile caching. */
self.addEventListener('push', event => {
  let payload;
  try { payload = event.data?.json(); } catch { return; }
  if (!payload || typeof payload !== 'object') return;
  const text = value => typeof value === 'string' ? value.slice(0, 300) : '';
  const target = new URL('/', self.location.origin);
  if (typeof payload.location_id === 'string') target.searchParams.set('clinic', payload.location_id);
  target.hash = 'incidents';
  event.waitUntil(self.registration.showNotification('Cold Chain · demo scenario', {
    body: text(payload.message) || 'A clinic incident was recorded.',
    tag: `coldchain-${text(String(payload.id ?? 'incident'))}`,
    data: { url: target.href },
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  let target = new URL('/', self.location.origin);
  try {
    const candidate = new URL(event.notification.data?.url || '/', self.location.origin);
    if (candidate.origin === self.location.origin && ['https:', 'http:'].includes(candidate.protocol) && !candidate.username && !candidate.password) target = candidate;
  } catch { /* Keep the safe same-origin root. */ }
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const client = windows.find(item => item.url === target.href);
    if (client) return client.focus();
    return self.clients.openWindow(target.href);
  })());
});
