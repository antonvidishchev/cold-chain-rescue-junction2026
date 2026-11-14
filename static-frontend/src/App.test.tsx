import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import App, { IncidentCard } from './App';
import { catalogueClinics } from './clinic-fixtures';
import { connectivity, measurement, normalizeBase, request, type Clinic, type Incident } from './api';
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
    if (/\/devices\/[^/]+\/inventory$/.test(url.pathname)) return Promise.resolve(new Response('', { status: 404 }));
    return Promise.resolve(json([]));
  });
}
describe('public dashboard', () => {
  it('shows the catalogue main site and ten unmonitored partners without false device states', async () => {
    const fetcher = mockApi(url => url.pathname.endsWith('/clinics') ? Promise.resolve(json([
      ...catalogueClinics.slice(1), catalogueClinics[0], { ...clinics[1], active: false },
    ])) : undefined);
    vi.stubGlobal('fetch', fetcher);
    render(<App />);
    expect(await screen.findByRole('heading', { name: /Espoonlahti Clinic.*Main monitored site/ })).toBeInTheDocument();
    const list = screen.getByLabelText('Choose a clinic');
    expect(within(list).getAllByRole('button')).toHaveLength(11);
    for (const site of catalogueClinics.slice(1)) {
      const row = within(list).getByRole('button', { name: new RegExp(site.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
      expect(row).toHaveTextContent('Not monitored / estimated capacity');
      expect(row).not.toHaveTextContent(/Offline|Awaiting device|No active incident|In range|°C reading/);
      await userEvent.click(row);
      expect(screen.getByRole('heading', { name: new RegExp(site.id) })).toBeInTheDocument();
      expect(screen.queryByText('Sensor temperature')).not.toBeInTheDocument();
      expect(screen.queryByText(/Reported on|Waiting for the first temperature/)).not.toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Device event reports' })).not.toBeInTheDocument();
    }
    expect(screen.getByText('172 km')).toBeInTheDocument();
    expect(screen.getByText('120 min')).toBeInTheDocument();
    expect(fetcher.mock.calls.some(([url]) => /location_id=(?!fridge-a)/.test(String(url)))).toBe(false);
    expect(fetcher.mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true);
  });
  it('selects live clinics, never substitutes temperatures or makes operator calls', async () => {
    const fetcher = mockApi(); vi.stubGlobal('fetch', fetcher);
    render(<App />);
    expect(await screen.findByRole('heading', { name: /Helsinki Demo Clinic.*Monitored site/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Espoo/ }));
    expect(await screen.findByRole('heading', { name: /Espoo Demo Clinic.*Monitored site/ })).toBeInTheDocument();
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
    await screen.findByRole('heading', { name: /Helsinki Demo Clinic.*Monitored site/ });
    await waitFor(() => expect(resolveOld).toBeDefined());
    await userEvent.click(screen.getByRole('button', { name: /^Espoo/ }));
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => resolveOld(json([{ id: 991, ts: now, temp_c: 99, stale: false, alarm_active: true }])));
    expect(screen.getByRole('heading', { name: /Espoo Demo Clinic.*Monitored site/ })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /99 degrees/ })).not.toBeInTheDocument();
  });
  it('renders watchdog mismatch, nullable codes and knob completion without claiming recovery', async () => {
    const fetcher = mockApi(url => {
      if (url.pathname.endsWith('/clinics')) return Promise.resolve(json([{ ...clinics[0], reported_temp_c: 4, reported_temp_at: now, power_on: false }]));
      if (url.pathname.endsWith('/alerts')) return Promise.resolve(json([{ id: 81, location_id: 'fridge-a', type: 'TAMPER', message: 'Display disagreement', status: 'acknowledged', created_at: now, recovered_at: null, protocol: 'H1', checklist: [], device_acknowledged_at: now, device_acknowledged_by: 'knob', device_resolved_at: now, device_resolved_by: 'knob', device_reported_protocol: 'H1', assessment_source: 'device_unverified' }]));
      if (url.pathname.endsWith('/readings')) return Promise.resolve(json([{ id: 1, ts: now, temp_c: 9, fridge_display_temp_c: 4, humidity: 65, stale: false }, { id: 2, ts: now, temp_c: 8, fridge_display_temp_c: null, humidity: null, stale: false }]));
      if (url.pathname.endsWith('/events')) return Promise.resolve(json([
        { id: 'tamper', device_id: 'unoq-fridge-a', event: 'fridge_tamper', ts: now, data: { sensor_temp_c: 9, fridge_display_temp_c: 4, mismatch_c: 5, fridge_mode: 'cooling', fridge_power_w: 80, stocked_items: ['demo-product'], code: 'H1' }, result: { stale: true } },
        { id: 'ack', event_type: 'alarm_acknowledged', ts: now, data: { alarm_kind: null, code: null, doors: false, acknowledged_by: 'knob' } },
        { id: 'resolve', event: 'alarm_resolved', ts: now, data: { alarm_kind: 'tamper', code: 'H1', acknowledged_at: Date.parse(now) / 1000, resolved_by: 'knob' } },
        { id: 'resolve-null', event: 'alarm_resolved', ts: now, data: { alarm_kind: 'power_outage', code: null, acknowledged_at: null, resolved_by: 'knob' } },
      ]));
      return undefined;
    });
    vi.stubGlobal('fetch', fetcher); render(<App />);
    const events = await screen.findByRole('region', { name: 'Device event reports' });
    expect(await within(events).findByText('Reported mismatch')).toBeInTheDocument();
    expect(within(events).getByText('5.0° C')).toBeInTheDocument();
    expect(within(events).getAllByText('Code H1')).toHaveLength(2);
    expect(within(events).queryByText(/Code null/)).not.toBeInTheDocument();
    expect(within(events).getByText('Alarm kind: Not reported')).toBeInTheDocument();
    expect(within(events).getByText('Acknowledged: Not reported')).toBeInTheDocument();
    expect(within(events).getByText(/Doors: closed/)).toBeInTheDocument();
    expect(within(events).getByText('Late report · not current state')).toBeInTheDocument();
    expect(screen.getByText('Protocol H1')).toBeInTheDocument();
    expect(screen.getByText(/Device assessment is unverified/)).toBeInTheDocument();
    expect(screen.getByText(/Device knob completion reported/)).toHaveTextContent('does not establish power or temperature recovery');
    expect(screen.queryByText(/Recovery observed/)).not.toBeInTheDocument();
    expect(screen.getByText('Reported off')).toBeInTheDocument();
    expect(screen.getByText('Fridge display (reported)')).toBeInTheDocument();
    await userEvent.click(screen.getByText('View accessible observation table'));
    const history = screen.getByRole('region', { name: 'Temperature observations' });
    expect(within(history).getByRole('columnheader', { name: 'Fridge display °C' })).toBeInTheDocument();
    expect(within(history).getByRole('cell', { name: '65' })).toBeInTheDocument();
    expect(within(history).getAllByRole('cell', { name: '—' })).toHaveLength(2);
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('/events?location_id=fridge-a&limit=50'))).toBe(true);
  });
  it.each([25, null])('preserves legacy protocol %s without requiring device annotations', async protocol => {
    vi.stubGlobal('fetch', mockApi(url => url.pathname.endsWith('/alerts') ? Promise.resolve(json([{ id: 91, location_id: 'fridge-a', type: 'POWER_LOSS', message: 'Power interrupted', status: 'open', created_at: now, recovered_at: null, protocol, checklist: [] }])) : undefined));
    render(<App />);
    expect(await screen.findByText(protocol == null ? 'Response checklist' : 'Protocol 25')).toBeInTheDocument();
    expect(screen.queryByText(/Device knob completion reported/)).not.toBeInTheDocument();
  });
  it('shows non-404 inventory failures in the inventory panel rather than treating them as missing snapshots', async () => {
    vi.stubGlobal('fetch', mockApi(url => url.pathname.endsWith('/inventory') ? Promise.resolve(new Response('', { status: 503 })) : undefined));
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('503');
    expect(screen.queryByText('No inventory sync received for this device.')).not.toBeInTheDocument();
    expect(screen.getByText('Connected to service')).toBeInTheDocument();
  });
  it('keeps observed stock and transfers separate from canonical capacity, treating 404 as no sync', async () => {
    vi.stubGlobal('fetch', mockApi(url => {
      if (url.pathname.endsWith('/clinics')) return Promise.resolve(json([{ ...clinics[0], used_units: 7, free_units: 3, devices: [...clinics[0].devices, { id: 'unsynced', last_seen: now, status: 'nominal' }, { id: 'empty', last_seen: now, status: 'nominal' }] }]));
      if (url.pathname.endsWith('/devices/unoq-fridge-a/inventory')) return Promise.resolve(json({ device_id: 'unoq-fridge-a', location_id: 'fridge-a', ts: now, inventory: [{ id: 'observed-vial', quantity: 99 }], transferred: [{ id: 'moved-vial', quantity: 6 }], stock_present: true, canonical_stock_updated: false }));
      if (url.pathname.endsWith('/devices/empty/inventory')) return Promise.resolve(json({ device_id: 'empty', location_id: 'fridge-a', ts: now, inventory: [], stock_present: false, canonical_stock_updated: false }));
      return undefined;
    }));
    render(<App />);
    expect(await screen.findByText('observed-vial')).toBeInTheDocument();
    expect(screen.getByText('7 units used · 3 units free')).toBeInTheDocument();
    expect(screen.getByText('moved-vial × 6')).toBeInTheDocument();
    expect(screen.getByText(/do not update canonical totals/)).toBeInTheDocument();
    expect(screen.getByText('No inventory sync received for this device.')).toBeInTheDocument();
    expect(screen.getByText('Empty device inventory snapshot.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText(/Device-local simulated camera frames appear here only after upload/)).toBeInTheDocument();
  });
  it('aborts event and snapshot requests and ignores late results after changing clinic', async () => {
    const pending: { resolve: (response: Response) => void; signal?: AbortSignal | null; path: string }[] = [];
    const fallback = mockApi();
    vi.stubGlobal('fetch', (input: string, options?: RequestInit) => {
      const url = new URL(input, window.location.origin);
      if ((url.pathname.endsWith('/events') && url.searchParams.get('location_id') === 'fridge-a') || url.pathname.endsWith('/devices/unoq-fridge-a/inventory')) {
        return new Promise<Response>(resolve => pending.push({ resolve, signal: options?.signal, path: url.pathname }));
      }
      return fallback(input, options);
    });
    render(<App />);
    await waitFor(() => expect(pending).toHaveLength(2));
    await userEvent.click(screen.getByRole('button', { name: /^Espoo/ }));
    expect(pending.every(item => item.signal?.aborted)).toBe(true);
    await act(async () => { for (const item of pending) item.resolve(json(item.path.endsWith('/events') ? [{ id: 'late', event: 'late_helsinki_event', ts: now }] : { inventory: [{ id: 'late-helsinki-stock', quantity: 1 }], ts: now, stock_present: true })); });
    expect(screen.queryByText('late helsinki event')).not.toBeInTheDocument();
    expect(screen.queryByText('late-helsinki-stock')).not.toBeInTheDocument();
    expect(await screen.findByText('No inventory sync received for this device.')).toBeInTheDocument();
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
    expect(screen.getByRole('img', { name: /Synthetic camera/ })).toHaveAttribute('src', expect.stringContaining('/images/public/content'));
  });
});
const publicIncident = (): Incident => ({
  id: 101, location_id: 'fridge-a', type: 'POWER_LOSS', message: 'Power interrupted', status: 'open',
  created_at: now, recovered_at: null, protocol: null, user_resolved_at: null, resolution_source: null,
  checklist: ['inspect', 'protect', 'verify'].map(id => ({ id, label: `Legacy ${id} label`, done: false })),
});
describe('public incident checklist', () => {
  it('sends only public endpoint patches and resolves only on the third persisted confirmation', async () => {
    let stored = publicIncident();
    const fetcher = vi.fn((input: string, options?: RequestInit) => {
      const id = new URL(input).pathname.split('/').at(-1);
      stored = { ...stored, checklist: stored.checklist.map(item => item.id === id ? { ...item, done: JSON.parse(String(options?.body)).done } : item) };
      if (stored.checklist.every(item => item.done)) stored = { ...stored, status: 'resolved_by_user', user_resolved_at: now, resolution_source: 'public_checklist' };
      return Promise.resolve(json(stored));
    });
    vi.stubGlobal('fetch', fetcher);
    const onSaved = vi.fn();
    render(<IncidentCard incident={publicIncident()} timeline={[]} onSaved={onSaved} />);
    expect(screen.queryByText(/Legacy/)).not.toBeInTheDocument();
    for (const label of ['Unit is inspected', 'Incident acted upon. Stock transferred to another unit or location', 'Recovery verified']) {
      await userEvent.click(screen.getByRole('checkbox', { name: label }));
      await waitFor(() => expect(screen.getByRole('checkbox', { name: label })).toBeChecked());
      if (label !== 'Recovery verified') expect(screen.queryByText('Resolved by user', { exact: true })).not.toBeInTheDocument();
    }
    expect(screen.getByText('Resolved by user', { exact: true })).toHaveClass('neutral');
    expect(screen.getByText('User confirmation; does not change measured temperature, power or inventory')).toBeInTheDocument();
    expect(screen.queryByText(/Recovery observed|sensor recovery/i)).not.toBeInTheDocument();
    for (const checkbox of screen.getAllByRole('checkbox')) expect(checkbox).toBeDisabled();
    expect(onSaved).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls.map(([url]) => new URL(url).pathname)).toEqual(['inspect', 'protect', 'verify'].map(id => `/api/alerts/101/public-checklist/${id}`));
    for (const [, options] of fetcher.mock.calls) {
      expect(options).toMatchObject({ method: 'PATCH', credentials: 'omit', headers: { 'Content-Type': 'application/json' }, body: '{"done":true}' });
      expect(options?.headers).not.toHaveProperty('Authorization');
    }
  });
  it('disables the entire checklist while pending, allows unchecking unresolved items and resists stale polling', async () => {
    let complete!: (response: Response) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { complete = resolve; })).mockResolvedValueOnce(json(publicIncident()));
    vi.stubGlobal('fetch', fetcher);
    const original = publicIncident();
    const { rerender } = render(<IncidentCard incident={original} timeline={[]} />);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Unit is inspected' }));
    for (const checkbox of screen.getAllByRole('checkbox')) expect(checkbox).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Unit is inspected' })).not.toBeChecked();
    const saved = { ...original, checklist: original.checklist.map(item => ({ ...item, done: item.id === 'inspect' })) };
    await act(async () => complete(json(saved)));
    rerender(<IncidentCard incident={{ ...original }} timeline={[]} />);
    expect(screen.getByRole('checkbox', { name: 'Unit is inspected' })).toBeChecked();
    rerender(<IncidentCard incident={saved} timeline={[]} />);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Unit is inspected' }));
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Unit is inspected' })).not.toBeChecked());
    expect(fetcher.mock.calls[1][1].body).toBe('{"done":false}');
    rerender(<IncidentCard incident={{ ...saved }} timeline={[]} />);
    expect(screen.getByRole('checkbox', { name: 'Unit is inspected' })).not.toBeChecked();
    rerender(<IncidentCard incident={publicIncident()} timeline={[]} />);
    const next = { ...saved, checklist: saved.checklist.map(item => ({ ...item, done: item.id === 'protect' })) };
    rerender(<IncidentCard incident={next} timeline={[]} />);
    expect(screen.getByRole('checkbox', { name: 'Incident acted upon. Stock transferred to another unit or location' })).toBeChecked();
  });
  it('does not falsely resolve or persist failed final confirmation and supports retry', async () => {
    const incident = publicIncident();
    incident.checklist[0].done = incident.checklist[1].done = true;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private diagnostics', { status: 503 })));
    render(<IncidentCard incident={incident} timeline={[]} />);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Recovery verified' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('503');
    expect(screen.getByRole('alert')).not.toHaveTextContent('private diagnostics');
    expect(screen.getByRole('checkbox', { name: 'Recovery verified' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Recovery verified' })).toBeEnabled();
    expect(screen.queryByText('Resolved by user', { exact: true })).not.toBeInTheDocument();
  });
  it.each(['resolved_by_user', 'resolved'])('renders resolved history %s without warning colors or editable controls', status => {
    render(<IncidentCard incident={{ ...publicIncident(), status, recovered_at: status === 'resolved_by_user' ? now : null }} timeline={[]} />);
    for (const checkbox of screen.getAllByRole('checkbox')) expect(checkbox).toBeDisabled();
    expect(document.querySelector('.incident-symbol')).toHaveClass('recovered');
    expect(document.querySelector('.incident-card .badge')).toHaveClass('neutral');
    expect(screen.queryByText(/Recovery observed/)).not.toBeInTheDocument();
    if (status === 'resolved_by_user') expect(screen.getByText(/Resolved by user/, { selector: 'p' })).toHaveTextContent('Not observed');
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
