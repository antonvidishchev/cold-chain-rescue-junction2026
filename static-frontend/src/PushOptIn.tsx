import { useState } from 'react';
import { API_BASE, request } from './api';
import { base64url, decodeKey } from './pushEncoding';
const storageKey = `coldchain.push.v1:${API_BASE}`;
type Saved = { id: string; token: string; endpoint: string };
function saved(): Saved | null {
  try { const value = JSON.parse(localStorage.getItem(storageKey) || 'null'); return value?.id && value?.token && value?.endpoint ? value : null; } catch { return null; }
}
export default function PushOptIn() {
  const supported = typeof Notification !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && window.isSecureContext;
  const [record, setRecord] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [permission, setPermission] = useState(supported ? Notification.permission : 'default');
  async function enable() {
    setBusy(true); setMessage('');
    let subscription: PushSubscription | null = null;
    let created = false;
    try {
      // Request directly from the click handler, before network or registration work.
      const granted = await Notification.requestPermission(); setPermission(granted);
      if (granted !== 'granted') { setMessage('Permission was not granted. Change it in your browser site settings.'); return; }
      localStorage.setItem(`${storageKey}:check`, '1'); localStorage.removeItem(`${storageKey}:check`);
      const { public_key } = await request<{ public_key: string }>('/push/public-key');
      const registration = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      subscription = await registration.pushManager.getSubscription();
      if (!subscription) { subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: decodeKey(public_key) }); created = true; }
      const previous = saved();
      const p256dh = subscription.getKey('p256dh'), auth = subscription.getKey('auth');
      if (!p256dh || !auth) throw new Error('Browser did not provide subscription keys.');
      const response = await request<{ id: string; removal_token?: string }>('/push/subscriptions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: subscription.endpoint, keys: { p256dh: base64url(p256dh), auth: base64url(auth) }, clinic_ids: [], ...(previous?.endpoint === subscription.endpoint ? { removal_token: previous.token } : {}) }) });
      const token = response.removal_token || (previous?.id === response.id ? previous.token : '');
      if (!token) throw new Error('This subscription has no saved removal token. Remove site push permissions and enable again to create a new subscription.');
      const next = { id: response.id, token, endpoint: subscription.endpoint };
      try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch {
        await request(`/push/subscriptions/${encodeURIComponent(next.id)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${next.token}` } });
        throw new Error('Browser storage is unavailable; subscription was not saved.');
      }
      setRecord(next); setMessage('Enabled for all fictional clinics on this browser. Delivery is best effort.');
    } catch (error) {
      if (created && subscription) await subscription.unsubscribe().catch(() => false);
      setMessage(error instanceof Error ? error.message : 'Could not enable notifications.');
    } finally { setBusy(false); }
  }
  async function disable() {
    if (!record) return;
    setBusy(true); setMessage('');
    try {
      await request(`/push/subscriptions/${encodeURIComponent(record.id)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${record.token}` } });
      const registration = await navigator.serviceWorker.getRegistration('/');
      await (await registration?.pushManager.getSubscription())?.unsubscribe();
      localStorage.removeItem(storageKey); setRecord(null); setMessage('Notifications disabled for this browser.');
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not remove subscription. Please retry.'); }
    finally { setBusy(false); }
  }
  return <section className="push-panel" aria-labelledby="push-heading"><div><span className="eyebrow">STAY INFORMED</span><h3 id="push-heading">A heads-up, not an alarm system.</h3><p>Optional browser notifications for this public demo. No patient data. Not for emergency or clinical use.</p></div><div className="push-actions">{!supported ? <span>Push unavailable. Use a supported browser on HTTPS or localhost.</span> : <><button className="button dark" onClick={enable} disabled={busy || permission === 'denied'}>{busy ? 'Please wait…' : record ? 'Renew notifications' : 'Enable notifications'}</button>{record && <button className="button" onClick={disable} disabled={busy}>Disable notifications</button>}{permission === 'denied' && <p>Notifications blocked in browser settings.</p>}</>}<p role="status">{message}</p></div></section>;
}
