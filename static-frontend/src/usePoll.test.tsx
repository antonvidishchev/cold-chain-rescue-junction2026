import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { usePoll } from './usePoll';

afterEach(() => vi.useRealTimers());

it('polls five seconds after completion without overlap and stops on unmount', async () => {
  vi.useFakeTimers();
  let finish!: (value: string) => void;
  const load = vi.fn(() => new Promise<string>(resolve => { finish = resolve; }));
  const { unmount } = renderHook(() => usePoll('events', load));
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => { finish('received'); });
  await act(async () => { await vi.advanceTimersByTimeAsync(4_999); });
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(load).toHaveBeenCalledTimes(2);
  unmount();
  await act(async () => { finish('late'); await vi.advanceTimersByTimeAsync(10_000); });
  expect(load).toHaveBeenCalledTimes(2);
});
