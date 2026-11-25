import { QueryClient, QueryClientProvider, useQuery, type QueryKey } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { useRecordEvents } from './hooks';
import { RealtimeProvider } from './RealtimeProvider';
import { scriptedRealtime } from './testing';
import type { RealtimeMessage } from './types';

// `covers` (architecture.md §8.3): the hook refreshes what a screen shows on every refresh, so a
// handler that filters on message types can no longer drop the catch-up or a lost channel.

function setup() {
  const realtime = scriptedRealtime();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidated: QueryKey[] = [];
  const spy = vi.spyOn(queryClient, 'invalidateQueries');
  spy.mockImplementation((filters) => {
    if (filters?.queryKey !== undefined) invalidated.push(filters.queryKey);
    return Promise.resolve();
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <RealtimeProvider tenantId="t1" userId="u1" factory={realtime.factory}>
        {children}
      </RealtimeProvider>
    </QueryClientProvider>
  );
  /** The record channels followed (the provider follows the personal and tenant ones too). */
  const records = () => realtime.channels().filter((c) => c.includes(':wi:'));
  /** The record keys invalidated (the provider refreshes its own session keys as well). */
  const recordKeys = () => invalidated.filter((k) => k[0] === 'wi');
  return { realtime, records, recordKeys, queryClient, spy, invalidated, wrapper };
}

/** A screen's handler that only knows its own event type (the pattern that dropped refresh). */
function filtered(seen: RealtimeMessage[]) {
  return (m: RealtimeMessage) => {
    seen.push(m);
  };
}

describe('channel hooks with covers', () => {
  it("a refresh refreshes the covered keys before a type-filtered handler, which can't drop it", async () => {
    const { realtime, invalidated, wrapper } = setup();
    const seen: RealtimeMessage[] = [];
    renderHook(
      () => {
        useRecordEvents('wi', 'r1', filtered(seen), { covers: [['wi', 'detail', 'r1']] });
      },
      { wrapper },
    );
    await waitFor(() => {
      expect(realtime.channels()).toContain('t:t1:wi:r1');
    });
    invalidated.length = 0;
    seen.length = 0;
    act(() => {
      realtime.publish('wi:r1', { type: 'refresh', ids: [] });
    });
    expect(invalidated).toEqual([['wi', 'detail', 'r1']]);
    expect(seen).toHaveLength(1);
    expect(seen[0]?.covered).toBe(true); // the handler needn't refresh those keys again
    // An ordinary event passes through untouched; covers aren't refreshed for it.
    invalidated.length = 0;
    act(() => {
      realtime.publish('wi:r1', { type: 'x.changed', ids: ['r1'] });
    });
    expect(invalidated).toEqual([]);
    expect(seen[1]?.covered).toBeUndefined();
  });

  it('new covers with a new id: one subscription, and the new key is the one refreshed', async () => {
    const { realtime, records, invalidated, wrapper } = setup();
    const { rerender } = renderHook(
      ({ id }: { id: string }) => {
        useRecordEvents('wi', id, () => undefined, { covers: [['wi', 'detail', id]] });
      },
      { wrapper, initialProps: { id: 'r1' } },
    );
    await waitFor(() => {
      expect(records()).toEqual(['t:t1:wi:r1']);
    });
    // A new options object on every render never re-subscribes.
    rerender({ id: 'r1' });
    expect(records()).toEqual(['t:t1:wi:r1']);
    rerender({ id: 'r2' });
    await waitFor(() => {
      expect(records()).toEqual(['t:t1:wi:r2']);
    });
    invalidated.length = 0;
    act(() => {
      realtime.publish('wi:r2', { type: 'refresh', ids: [] });
    });
    expect(invalidated).toEqual([['wi', 'detail', 'r2']]);
  });

  it('the first-subscribe catch-up refreshes a covered query with data', async () => {
    const { realtime, queryClient, spy, wrapper } = setup();
    let fetches = 0;
    queryClient.setQueryData(['wi', 'detail', 'r1'], { v: 0 });
    spy.mockRestore();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    renderHook(
      () => {
        useQuery({
          queryKey: ['wi', 'detail', 'r1'],
          queryFn: () => {
            fetches += 1;
            return { v: fetches };
          },
          staleTime: Infinity,
        });
        useRecordEvents('wi', 'r1', () => undefined, { covers: [['wi', 'detail', 'r1']] });
      },
      { wrapper },
    );
    await waitFor(() => {
      expect(realtime.channels()).toContain('t:t1:wi:r1');
    });
    // The scripted subscription goes live with no recovery: a first-subscribe catch-up.
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalled();
    });
    expect(
      invalidate.mock.calls.some(([f]) => JSON.stringify(f?.queryKey) === '["wi","detail","r1"]'),
    ).toBe(true);
  });

  it('without covers, a handler still gets the refresh as before (unmarked)', async () => {
    const { realtime, recordKeys, wrapper } = setup();
    const seen: RealtimeMessage[] = [];
    renderHook(
      () => {
        useRecordEvents('wi', 'r1', filtered(seen));
      },
      { wrapper },
    );
    await waitFor(() => {
      expect(realtime.channels()).toContain('t:t1:wi:r1');
    });
    seen.length = 0;
    act(() => {
      realtime.publish('wi:r1', { type: 'refresh', ids: [] });
    });
    expect(recordKeys()).toEqual([]);
    expect(seen[0]?.covered).toBeUndefined();
  });

  it('a record hook with no id yet joins nothing and refreshes nothing', () => {
    const { records, recordKeys, wrapper } = setup();
    renderHook(
      () => {
        useRecordEvents('wi', undefined, () => undefined, { covers: [['wi', 'detail']] });
      },
      { wrapper },
    );
    expect(records()).toEqual([]);
    expect(recordKeys()).toEqual([]);
  });
});
