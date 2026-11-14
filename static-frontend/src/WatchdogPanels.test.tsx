import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { WatchdogEvents } from './WatchdogPanels';
import { catalogueClinics } from './clinic-fixtures';
import type { Incident } from './api';

const feed = vi.hoisted(() => ({ data: [] as unknown[], updated: '2026-11-14T16:00:00Z', loading: false }));
vi.mock('./usePoll', () => ({ usePoll: () => feed }));

it('restores expandable coloured events and attaches checklists only to matching accepted incidents', async () => {
  const time = '2026-11-14T16:00:00Z';
  feed.data = [
    { id: 'alarm', event: 'doors_open', ts: time, data: {}, result: { stale: false } },
    { id: 'late', event: 'doors_open', ts: time, data: {}, result: { stale: true } },
    { id: 'normal', event: 'telemetry', ts: time, data: { temp_c: 5.2, alarm: null } },
    { id: 'done', event: 'alarm_resolved', ts: time, data: { alarm_kind: 'unfreeze', acknowledged_at: null } },
  ];
  const incident = { id: 42, type: 'DOORS_OPEN', status: 'acknowledged', created_at: time } as Incident;
  const { container } = render(<WatchdogEvents clinic={catalogueClinics[0]} incidents={[incident]} renderIncident={() => <input type="checkbox" aria-label="Unit is inspected" />} />);
  const cards = container.querySelectorAll<HTMLDetailsElement>('.event-card');
  expect(cards).toHaveLength(4);
  expect(cards[0].open).toBe(false);
  expect(within(cards[0]).getByText('Acknowledged')).toHaveClass('warning');
  expect(within(cards[1]).getByText('Late report')).toHaveClass('warning');
  expect(within(cards[2]).getByText('No alarm')).toHaveClass('good');
  expect(within(cards[3]).getByText('Resolved')).toHaveClass('good');
  expect(container.querySelectorAll('input[type=checkbox]')).toHaveLength(1);
  await userEvent.click(cards[0].querySelector('summary')!);
  expect(cards[0].open).toBe(true);
  const checkbox = screen.getByRole('checkbox', { name: 'Unit is inspected' });
  await userEvent.click(checkbox);
  expect(checkbox).toBeChecked();
});
