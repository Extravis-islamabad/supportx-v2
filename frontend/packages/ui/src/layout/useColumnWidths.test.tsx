import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { ListKind } from '@supportx/api-client';
import { fakeApi } from '@supportx/api-client/testing';

import { renderUi } from '../test/render';
import { useColumnWidths } from './useColumnWidths';

// WP-049b s4a: the hook takes the shared store's kinds (assets) beside the work-item types.
// Work-item lists must keep reading and writing their own type's /list-settings, never the
// shared /api/v1/list-settings/; "Reset widths" clears the saved widths in both stores.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function Widths({ kind }: { kind: ListKind }) {
  const widths = useColumnWidths({
    kind,
    viewKey: 'all',
    keys: ['name', 'tag'],
    label: (key) => `Width of ${key}`,
  });
  return (
    <div>
      <span data-testid="name-width">{String(widths.width('name') ?? 'auto')}</span>
      <span data-testid="changed">{String(widths.changed)}</span>
      <button type="button" onClick={widths.reset}>
        reset
      </button>
    </div>
  );
}

const saved = (key: string) => ({
  view_key: key,
  columns: [
    { key: 'name', width: 300 },
    { key: 'tag', width: null },
  ],
  sort: null,
  page_size: 50,
  version: 4,
});

describe('useColumnWidths: which store each list uses', () => {
  it('an incident list reads and writes its own list-settings, never the shared store', async () => {
    const fake = fakeApi({
      'GET /api/v1/incidents/list-settings/all': { body: saved('all') },
      'PUT /api/v1/incidents/list-settings/all': { body: { ...saved('all'), version: 5 } },
    });
    restore = fake.restore;
    renderUi(<Widths kind="incidents" />);
    await waitFor(() => {
      expect(screen.getByTestId('name-width').textContent).toBe('300');
    });
    fireEvent.click(screen.getByText('reset'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/incidents/list-settings/all')).toHaveLength(1);
    });
    const shared = fake.calls.filter((c) => c.path.startsWith('/api/v1/list-settings/'));
    expect(shared).toEqual([]);
    const [put] = fake.find('PUT', '/api/v1/incidents/list-settings/all');
    expect(put?.headers.get('If-Match')).toBe('"4"');
  });

  it('a shared list (assets) uses the shared store, and reset clears every saved width', async () => {
    const fake = fakeApi({
      'GET /api/v1/list-settings/assets/views/all': { body: { ...saved('all'), favourite: true } },
      'PUT /api/v1/list-settings/assets/views/all': {
        body: { ...saved('all'), columns: [], favourite: true, version: 5 },
      },
    });
    restore = fake.restore;
    renderUi(<Widths kind="assets" />);
    await waitFor(() => {
      expect(screen.getByTestId('changed').textContent).toBe('true');
    });
    fireEvent.click(screen.getByText('reset'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/list-settings/assets/views/all')).toHaveLength(1);
    });
    const [put] = fake.find('PUT', '/api/v1/list-settings/assets/views/all');
    const body = put?.body as {
      columns: { key: string; width: number | null }[];
      favourite?: unknown;
    };
    expect(body.columns.every((c) => c.width === null)).toBe(true);
    // A widths save never touches the star: it is left out, so the server keeps it.
    expect(body.favourite).toBeUndefined();
    expect(put?.headers.get('If-Match')).toBe('"4"');
    expect(fake.calls.some((c) => c.path.includes('/incidents/'))).toBe(false);
    await waitFor(() => {
      expect(screen.getByTestId('changed').textContent).toBe('false');
    });
  });
});
