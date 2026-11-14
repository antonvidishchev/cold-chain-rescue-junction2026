import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import PushOptIn from './PushOptIn';
import { base64url } from './pushEncoding';
import { API_BASE } from './api';
const storeKey = `coldchain.push.v1:${API_BASE}`;
function support(permission: NotificationPermission = 'default') {
  const permissionRequest = vi.fn().mockResolvedValue('granted');
  vi.stubGlobal('Notification', { permission, requestPermission: permissionRequest });
  vi.stubGlobal('PushManager', function () {});
  vi.stubGlobal('isSecureContext', true);
  const unsubscribe = vi.fn().mockResolvedValue(true);
  const subscription = { endpoint: 'https://fcm.googleapis.com/test', getKey: (key: string) => key === 'auth' ? new Uint8Array(16).buffer : new Uint8Array([4, ...new Array(64).fill(0)]).buffer, unsubscribe };
  const registration = { pushManager: { getSubscription: vi.fn().mockResolvedValue(subscription), subscribe: vi.fn().mockResolvedValue(subscription) } };
  vi.stubGlobal('navigator', { serviceWorker: { register: vi.fn().mockResolvedValue(registration), ready: Promise.resolve(registration), getRegistration: vi.fn().mockResolvedValue(registration) } });
  return { permissionRequest, registration, unsubscribe };
}
describe('push opt-in', () => {
  it('does not request permission or subscribe without a user gesture', () => {
    const { permissionRequest } = support();
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    render(<PushOptIn />);
    expect(permissionRequest).not.toHaveBeenCalled(); expect(fetcher).not.toHaveBeenCalled();
  });
  it('explains missing support', () => {
    vi.stubGlobal('Notification', undefined);
    render(<PushOptIn />);
    expect(screen.getByText(/Push unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enable notifications' })).not.toBeInTheDocument();
  });
  it('explains denied permission without asking again', () => {
    const { permissionRequest } = support('denied');
    render(<PushOptIn />);
    expect(screen.getByRole('button', { name: 'Enable notifications' })).toBeDisabled();
    expect(screen.getByText(/blocked in browser settings/)).toBeInTheDocument();
    expect(permissionRequest).not.toHaveBeenCalled();
  });
  it('persists the initial removal token, sends it on renewal, and authorizes deletion', async () => {
    support();
    let posted = 0;
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('public-key')) return new Response(JSON.stringify({ public_key: base64url(new Uint8Array([4, ...new Array(64).fill(0)]).buffer) }));
      if (options?.method === 'DELETE') return new Response(null, { status: 204 });
      posted++;
      return new Response(JSON.stringify(posted === 1 ? { id: 'subscription-id', removal_token: 'private-removal-token-32-characters' } : { id: 'subscription-id' }));
    });
    vi.stubGlobal('fetch', fetcher); render(<PushOptIn />);
    await userEvent.click(screen.getByRole('button', { name: 'Enable notifications' }));
    await screen.findByRole('button', { name: 'Renew notifications' });
    expect(JSON.parse(localStorage.getItem(storeKey)!)).toMatchObject({ token: 'private-removal-token-32-characters' });
    await userEvent.click(screen.getByRole('button', { name: 'Renew notifications' }));
    await waitFor(() => expect(posted).toBe(2));
    const posts = fetcher.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(JSON.parse(posts[1][1]!.body as string).removal_token).toBe('private-removal-token-32-characters');
    expect(JSON.parse(posts[0][1]!.body as string).keys.auth).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(JSON.parse(posts[0][1]!.body as string).keys.p256dh).toMatch(/^[A-Za-z0-9_-]{87}$/);
    await userEvent.click(screen.getByRole('button', { name: 'Disable notifications' }));
    await waitFor(() => expect(localStorage.getItem(storeKey)).toBeNull());
    const deletion = fetcher.mock.calls.find(([, options]) => options?.method === 'DELETE');
    expect(deletion?.[1]?.headers).toEqual({ Authorization: 'Bearer private-removal-token-32-characters' });
  });
  it('reports a missing public key without subscribing', async () => {
    const { registration } = support();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
    render(<PushOptIn />);
    await userEvent.click(screen.getByRole('button', { name: 'Enable notifications' }));
    expect(await screen.findByText(/Service request failed \(503\)/)).toBeInTheDocument();
    expect(registration.pushManager.subscribe).not.toHaveBeenCalled();
  });
});
