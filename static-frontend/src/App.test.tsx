import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import App from './App';
import { connectivity, measurement, normalizeBase, request, type Clinic } from './api';
vi.mock('./ClinicMap', () => ({ default: () => <div aria-label="Map stub" /> }));
const now = new Date().toISOString();
const clinic = (id: string, city: string, temp: number | null = null): Clinic => ({ id, city, clinic_id: city.toLowerCase(), name: `${city} Demo Clinic (fictional)`, synthetic: true, last_temp_c: temp, last_reading_at: temp == null ? null : now, alarm_state: 'NORMAL', power_on: true, effective_range: { min_c: 2, max_c: 8 }, devices: [{ id: `unoq-${id}`, last_seen: now, status: 'nominal' }], used_units: 0, free_units: 10 });
const clinics = [clinic('fridge-a', 'Helsinki', 4.5), clinic('fridge-b', 'Espoo', 5.1)];
const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } });
function mockApi(extra?: (url: URL) => Promise<Response> | undefined) {
  return vi.fn((input: string | URL, _options?: RequestInit) => {
    const url = new URL(String(input), window.location.origin);
    const custom = extra?.(url); if (custom) return custom;
    if (url.pathname.endsWith('/clinics')) return Promise.resolve(json(clinics));
    return Promise.resolve(json([]));
  });
}
describe('public dashboard', () => {
  it('selects live clinics, never substitutes temperatures or makes operator calls', async () => {
    const fetcher = mockApi(); vi.stubGlobal('fetch', fetcher);
    render(<App />);
    expect(await screen.findByRole('heading', { name: /Helsinki\s*Fictional clinic/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Espoo/ }));
    expect(await screen.findByRole('heading', { name: /Espoo\s*Fictional clinic/ })).toBeInTheDocument();
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).includes('location_id=fridge-b'))).toBe(true));
    expect(screen.getByText(/No public synthetic images/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    for (const [url, options] of fetcher.mock.calls) {
      expect(options?.method || 'GET').toBe('GET');
      expect(String(url)).not.toMatch(/ack|approve|commands|telemetry|sim\//);
      expect(JSON.stringify(options?.headers || {})).not.toMatch(/functions-key|device-key/i);
    }
  });
  it('shows API failures without fabricated healthy clinics', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('503');
    expect(screen.getByText('Service disconnected')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Helsinki/ })).not.toBeInTheDocument();
  });
  it('ignores aborted stale selection responses even when the transport resolves them', async () => {
    let resolveOld!: (value: Response) => void;
    let oldSignal: AbortSignal | null | undefined;
    const fetcher = mockApi(url => url.pathname.endsWith('/readings') && url.searchParams.get('location_id') === 'fridge-a' ? new Promise(resolve => { resolveOld = resolve; }) : undefined);
    vi.stubGlobal('fetch', (url: string, options?: RequestInit) => { if (url.includes('/readings?location_id=fridge-a')) oldSignal = options?.signal; return fetcher(url, options); });
    window.history.replaceState(null, '', '/'); render(<App />);
    await screen.findByRole('heading', { name: /Helsinki\s*Fictional clinic/ });
    await waitFor(() => expect(resolveOld).toBeDefined());
    await userEvent.click(screen.getByRole('button', { name: /^Espoo/ }));
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => resolveOld(json([{ id: 991, ts: now, temp_c: 99, stale: false, alarm_active: true }])));
    expect(screen.getByRole('heading', { name: /Espoo\s*Fictional clinic/ })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /99 degrees/ })).not.toBeInTheDocument();
  });
  it('filters private images and renders descriptions as text', async () => {
    vi.stubGlobal('fetch', mockApi(url => url.pathname.endsWith('/images') ? Promise.resolve(json([
      { id: 'private', synthetic: false, description: 'PRIVATE DATA', observed_at: now, updated_at: now },
      { id: 'public', synthetic: true, description: '<script>alert(1)</script>', observed_at: now, updated_at: now, status: 'completed' },
    ])) : undefined));
    render(<App />);
    expect(await screen.findByText('<script>alert(1)</script>')).toBeInTheDocument();
    expect(screen.queryByText('PRIVATE DATA')).not.toBeInTheDocument();
    expect(document.querySelector('.photo-description script')).toBeNull();
    expect(screen.getByRole('img', { name: /Synthetic demonstration/ })).toHaveAttribute('src', expect.stringContaining('/images/public/content'));
  });
});
describe('contract safeguards', () => {
  it('separates old connectivity from measured temperature', () => {
    const stale = { ...clinics[0], devices: [{ ...clinics[0].devices[0], last_seen: '2020-01-01T00:00:00Z' }] };
    expect(connectivity(stale)).toBe('Heartbeat stale');
    expect(measurement(stale)).toBe('In range at observation');
    expect(measurement(clinic('x', 'Unknown'))).toBe('No measurement');
  });
  it('supports empty same-origin base and rejects unsafe media origins', () => {
    expect(normalizeBase('')).toBe('');
    expect(normalizeBase('https://example.com/')).toBe('https://example.com');
    for (const value of ['javascript:alert(1)', 'https://user:password@example.com', 'https://example.com?key=secret', 'data:text/html,x']) expect(() => normalizeBase(value)).toThrow();
  });
  it('does not disclose backend error bodies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private diagnostics', { status: 500 })));
    await expect(request('/clinics')).rejects.toThrow('Service request failed (500)');
  });
});
