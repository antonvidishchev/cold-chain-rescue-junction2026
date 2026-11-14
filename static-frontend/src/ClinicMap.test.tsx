import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { catalogueClinics } from './clinic-fixtures';
import ClinicMap from './ClinicMap';

const leaflet = vi.hoisted(() => {
  const map = { fitBounds: vi.fn(), setView: vi.fn(), invalidateSize: vi.fn(), remove: vi.fn() };
  const layer = { addTo: vi.fn().mockReturnThis(), clearLayers: vi.fn() };
  const marker = { addTo: vi.fn().mockReturnThis(), bindTooltip: vi.fn(), on: vi.fn() };
  return { map: vi.fn(() => map), instance: map, layerGroup: vi.fn(() => layer), tileLayer: vi.fn(() => ({ addTo: vi.fn() })), divIcon: vi.fn(options => options), marker: vi.fn(() => marker) };
});
vi.mock('leaflet', () => ({ default: leaflet }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
});
describe('backend location map', () => {
  it('maps all eleven API positions, keeps destination markers neutral, and preserves zoom on selection/poll', () => {
    const select = vi.fn();
    const { rerender } = render(<ClinicMap clinics={catalogueClinics} selected="fridge-a" onSelect={select} />);
    expect(leaflet.marker).toHaveBeenCalledTimes(11);
    expect(leaflet.instance.fitBounds).toHaveBeenCalledWith(
      expect.arrayContaining(catalogueClinics.slice(0, 5).map(site => [site.lat, site.lon])), expect.anything());
    expect(leaflet.instance.fitBounds.mock.calls[0][0]).toHaveLength(5);
    for (const site of catalogueClinics) expect(leaflet.marker).toHaveBeenCalledWith([site.lat, site.lon], expect.objectContaining({ title: expect.stringContaining(site.name) }));
    expect(leaflet.divIcon.mock.calls.filter(([options]) => options.html.includes('destination'))).toHaveLength(10);
    for (const call of leaflet.marker.mock.calls.slice(1)) expect((call as unknown as [unknown, { title: string }])[1].title).toContain('Not monitored / estimated capacity');
    rerender(<ClinicMap clinics={catalogueClinics.map(site => ({ ...site }))} selected="tyks-turku" onSelect={select} />);
    expect(leaflet.instance.fitBounds).toHaveBeenCalledTimes(1);
    const moved = catalogueClinics.map((site, index) => index ? site : { ...site, lat: 61, lon: 25 });
    rerender(<ClinicMap clinics={moved} selected="tyks-turku" onSelect={select} />);
    expect(leaflet.instance.fitBounds).toHaveBeenCalledTimes(2);
    expect(leaflet.marker).toHaveBeenCalledWith([61, 25], expect.anything());
  });
  it('never invents positions for missing, nonnumeric, infinite or out-of-bounds API coordinates', () => {
    const invalid = [
      { lat: null, lon: null }, { lat: undefined, lon: undefined }, { lat: NaN, lon: 0 },
      { lat: 91, lon: 0 }, { lat: 0, lon: -181 }, { lat: 0, lon: Infinity },
      { lat: '60' as unknown as number, lon: 25 },
    ].map((coordinates, index) => ({ ...catalogueClinics[index], ...coordinates }));
    const { rerender } = render(<ClinicMap clinics={invalid} selected="" onSelect={() => {}} />);
    expect(leaflet.marker).not.toHaveBeenCalled();
    expect(leaflet.instance.fitBounds).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('No fallback locations are shown');
    rerender(<ClinicMap clinics={[...invalid, { ...catalogueClinics[10], lat: 0, lon: 0 }]} selected="" onSelect={() => {}} />);
    expect(leaflet.marker).toHaveBeenCalledTimes(1);
    expect(leaflet.marker).toHaveBeenCalledWith([0, 0], expect.anything());
    expect(screen.getByRole('status')).toHaveTextContent('7 sites have no valid coordinates');
  });
});
