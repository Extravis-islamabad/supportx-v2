import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { allOf, searchFilter, useUpdateUser, useUser, useUsers } from './users';
import { fakeApi, fakeUser } from './testing';

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('useUsers', () => {
  let restore: () => void = () => undefined;
  afterEach(() => {
    restore();
  });

  it('pages with the cursor and sends filter DSL + sort', async () => {
    const fake = fakeApi({
      'GET /api/v1/users': (c) =>
        c.url.searchParams.get('cursor') === null
          ? {
              body: {
                items: [fakeUser({ id: 'a' })],
                has_more: true,
                next_cursor: 'c2',
                estimated_total: 2,
              },
            }
          : { body: { items: [fakeUser({ id: 'b' })], has_more: false, next_cursor: null } },
    });
    restore = fake.restore;
    const filter = allOf(searchFilter('tar'), {
      field: 'user_type',
      op: 'eq',
      value: 'technician',
    });

    const { result } = renderHook(() => useUsers({ filter, sort: '-last_login_at', limit: 1 }), {
      wrapper,
    });
    await waitFor(() => {
      expect(result.current.data?.pages).toHaveLength(1);
    });
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });

    await waitFor(() => {
      expect(result.current.data?.pages).toHaveLength(2);
    });
    expect(result.current.data?.pages.flatMap((p) => p.items.map((u) => u.id))).toEqual(['a', 'b']);
    expect(result.current.hasNextPage).toBe(false);
    const [first, second] = fake.calls.map((c) => c.url.searchParams);
    expect(JSON.parse(first?.get('filter') ?? 'null')).toEqual({
      and: [
        {
          or: [
            { field: 'display_name', op: 'contains', value: 'tar' },
            { field: 'email', op: 'contains', value: 'tar' },
          ],
        },
        { field: 'user_type', op: 'eq', value: 'technician' },
      ],
    });
    expect(first?.get('sort')).toBe('-last_login_at');
    expect(first?.get('include_total')).toBe('true');
    expect(second?.get('cursor')).toBe('c2');
  });

  it('has no filter for an empty search', () => {
    expect(searchFilter('  ')).toBeUndefined();
    expect(allOf(undefined, undefined)).toBeUndefined();
  });
});

describe('useUpdateUser', () => {
  it('sends the version the form was built from, even after a newer ETag was seen', async () => {
    const path = `/api/v1/users/${fakeUser().id}`;
    const fake = fakeApi({
      [`GET ${path}`]: { body: fakeUser({ version: 5 }), headers: { ETag: '"5"' } },
      [`PATCH ${path}`]: {
        status: 409,
        body: { code: 'version_conflict', message_key: 'errors.version_conflict' },
      },
    });
    // A background refetch saw version 5 (someone else saved)...
    const { result: user } = renderHook(() => useUser(fakeUser().id), { wrapper });
    await waitFor(() => {
      expect(user.current.data?.version).toBe(5);
    });
    // ...but the form was loaded at version 3: the save must not silently overwrite.
    const { result } = renderHook(() => useUpdateUser(fakeUser().id), { wrapper });
    await act(async () => {
      await result.current
        .mutateAsync({ changes: { signature: 'x' }, version: 3 })
        .catch(() => undefined);
    });
    expect(fake.find('PATCH', path)[0]?.headers.get('If-Match')).toBe('"3"');
    fake.restore();
  });
});
