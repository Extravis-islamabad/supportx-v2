import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-053 S2, lane C's conditions 6, 8, 9, 10 and 13: the CI's Map tab (restricted placeholders,
// the keyboard, Escape closing only the menu, the list equivalent, truncation in words, live
// through one filtered list channel) and the Versions tab's compare.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const TYPE = 'a0000000-0000-7000-8000-000000000001';
const STATE = 'a0000000-0000-7000-8000-000000000002';
const CI = 'a0000000-0000-7000-8000-000000000003';
const OTHER = 'a0000000-0000-7000-8000-000000000004';
const RUNS_ON = 'a0000000-0000-7000-8000-000000000005';
const now = new Date().toISOString();

const ci = {
  id: CI,
  display_id: 'CI-1',
  name: 'Mail service',
  type_id: TYPE,
  state_id: STATE,
  site_id: null,
  owner_user_id: null,
  owner_group_id: null,
  managed_by_group_id: null,
  business_impact: null,
  criticality: null,
  asset_id: null,
  source: 'manual',
  updated_at: now,
  version: 3,
  description: null,
  created_at: now,
  created_by: null,
  updated_by: null,
  deleted_at: null,
  history_count: 0,
  can_edit: true,
  can_delete: true,
};

const node = (id: string, name: string, display: string) => ({
  key: id,
  restricted: false,
  depth: id === CI ? 0 : 1,
  id,
  display_id: display,
  name,
  type_id: TYPE,
  type_label_key: 'cmdb_ci_type.server',
  type_names: {},
  state_id: STATE,
  state_category: 'active',
  state_label_key: 'cmdb_ci_state.in_use',
  state_names: {},
  version: 1,
  counts: null,
});

function graph(truncated = false) {
  return {
    nodes: [
      node(CI, 'Mail service', 'CI-1'),
      node(OTHER, 'Server SRV-01', 'CI-2'),
      // A CI the reader may not open: its key only (lane C's condition 2).
      { key: 'r1', restricted: true, depth: 1 },
    ],
    edges: [
      {
        id: 'e0000000-0000-7000-8000-000000000001',
        type_id: RUNS_ON,
        from_key: CI,
        to_key: OTHER,
        version: 1,
      },
      { id: null, type_id: RUNS_ON, from_key: 'r1', to_key: CI, version: null },
    ],
    truncated,
    node_max: 500,
    counts_available: false,
  };
}

const relationshipType = {
  id: RUNS_ON,
  code: 'runs_on',
  built_in: true,
  names_forward: {},
  names_inverse: {},
  carries_impact: true,
  rules: [],
  relationship_count: 2,
  suggested: false,
  version: 1,
};

function api(options: { truncated?: boolean } = {}) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/cmdb/ci-types': {
        body: {
          items: [
            {
              id: TYPE,
              parent_id: null,
              api_name: 'server',
              built_in: true,
              names: {},
              icon: null,
              ci_count: 2,
              child_count: 0,
              version: 1,
            },
          ],
        },
      },
      'GET /api/v1/cmdb/ci-states': {
        body: {
          items: [
            {
              id: STATE,
              api_name: 'in_use',
              built_in: true,
              names: {},
              category: 'active',
              position: 0,
              version: 1,
            },
          ],
        },
      },
      'GET /api/v1/cmdb/settings': { body: { exclude_eol_from_pickers: true, version: 1 } },
      [`GET /api/v1/cmdb/cis/${CI}`]: { body: ci, headers: { ETag: '"3"' } },
      [`GET /api/v1/cmdb/cis/${CI}/history`]: {
        body: { items: [], has_more: false, next_cursor: null },
      },
      'GET /api/v1/cmdb/relationship-types': { body: { items: [relationshipType] } },
      [`GET /api/v1/cmdb/cis/${CI}/neighbours`]: { body: graph(options.truncated) },
      'GET /api/v1/cmdb/business-views': {
        body: { items: [], next_cursor: null, has_more: false, estimated_total: 0 },
      },
      'GET /api/v1/realtime/lists/cmdb': { body: { channels: ['t:tenant:cmdb:all'] } },
      [`GET /api/v1/cmdb/cis/${CI}/versions`]: {
        body: {
          items: [
            { version: 3, saved_at: now, saved_by: null, saved_by_name: 'Sara Khan' },
            { version: 2, saved_at: now, saved_by: null, saved_by_name: 'Sara Khan' },
          ],
          next_cursor: null,
        },
      },
      [`GET /api/v1/cmdb/cis/${CI}/compare`]: {
        body: {
          from_version: {
            version: 2,
            saved_at: now,
            saved_by: null,
            saved_by_name: null,
            fields: {},
            relationships: [],
          },
          to_version: {
            version: 3,
            saved_at: now,
            saved_by: null,
            saved_by_name: null,
            fields: {},
            relationships: [],
          },
          attributes: [
            { field: 'state_id', kind: 'changed', old: null, new: STATE },
            { field: 'description', kind: 'added', old: null, new: 'x'.repeat(400) },
            { field: 'owner_user_id', kind: 'changed', old: null, new: OTHER },
          ],
          relationships_added: [
            {
              id: null,
              type_id: RUNS_ON,
              direction: 'forward',
              ci: { key: 'r1', restricted: true },
            },
          ],
          relationships_removed: [
            {
              id: 'e0000000-0000-7000-8000-000000000002',
              type_id: RUNS_ON,
              direction: 'forward',
              ci: node(OTHER, 'Server SRV-01', 'CI-2'),
            },
          ],
        },
      },
    },
  });
  restore = fake.restore;
  return fake;
}

function Shown() {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App />
    </ConfigProvider>
  );
}

/** The React Flow node wrapper (the focusable element) of a map node. */
async function flowNode(key: string): Promise<HTMLElement> {
  const inner = await screen.findByTestId(`ci-map-node-${key}`);
  const wrapper = inner.closest<HTMLElement>('.react-flow__node');
  if (wrapper === null) throw new Error(`no React Flow node for ${key}`);
  return wrapper;
}

describe('CMDB › the Map tab', () => {
  it('draws a restricted CI neutral, in words, with no actions, and lists the map too', async () => {
    setDefaultClientFactory(inertClientFactory);
    api({ truncated: true });
    window.history.pushState({}, '', `/cmdb/${CI}?tab=map`);
    render(<Shown />);
    const restricted = await screen.findByTestId(`ci-map-node-${CI}~r1`);
    // Condition 8: "A CI you can't open", the neutral tone with a lock, a dotted border.
    expect(restricted.textContent).toContain("A CI you can't open");
    expect(restricted.getAttribute('data-restricted')).toBe('true');
    expect(
      within(restricted).getByText('No access').closest('[data-tone]')?.getAttribute('data-tone'),
    ).toBe('default');
    expect(restricted.textContent).not.toContain('r1');
    // Condition 6: each node is labelled with its name, type, state and links.
    const other = await flowNode(OTHER);
    expect(other.getAttribute('aria-label')).toBe('Server SRV-01, Server, In use, 1 relationship');
    expect((await flowNode(`${CI}~r1`)).getAttribute('aria-label')).toBe(
      "A CI you can't open, 1 relationship",
    );
    // A restricted node has no menu: Enter does nothing.
    fireEvent.keyDown(await flowNode(`${CI}~r1`), { key: 'Enter' });
    expect(screen.queryByTestId('ci-map-menu')).toBeNull();
    // The skip link leads to the same map as a list; the restricted row has no link and no ID.
    const skip = screen.getByTestId('ci-map-skip');
    expect(skip.textContent).toBe('Skip to the list');
    const list = screen.getByTestId('ci-map-list');
    expect(skip.getAttribute('href')).toBe(`#${list.id}`);
    const row = within(list).getByTestId(`ci-map-list-${CI}~r1`);
    expect(row.textContent).toContain("A CI you can't open");
    expect(row.querySelector('a')).toBeNull();
    expect(within(list).getByTestId(`ci-map-list-${CI}`).textContent).toContain('runs on');
    // Condition 10: truncation said in words.
    expect(screen.getByTestId('ci-map-truncated').textContent).toContain('Nodes shown: 3');
    // No raw code reaches the screen.
    expect(screen.getByTestId('ci-map-tab').textContent).not.toMatch(/runs_on|cmdb_|in_use/);
  });

  it('moves by the arrow keys, opens a menu on Enter and closes only the menu on Escape', async () => {
    setDefaultClientFactory(inertClientFactory);
    api();
    window.history.pushState({}, '', `/cmdb/${CI}?tab=map`);
    render(<Shown />);
    const base = await flowNode(CI);
    base.focus();
    // Radial: the two neighbours sit above and below the base.
    fireEvent.keyDown(base, { key: 'ArrowUp' });
    expect(document.activeElement).not.toBe(base);
    expect(document.activeElement?.classList.contains('react-flow__node')).toBe(true);
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(base);
    fireEvent.keyDown(base, { key: 'ArrowDown' });
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Home' });
    expect(document.activeElement).toBe(base);

    const other = await flowNode(OTHER);
    other.focus();
    fireEvent.keyDown(other, { key: 'Enter' });
    const menu = await screen.findByTestId('ci-map-menu');
    expect(within(menu).getByTestId('ci-map-menu-open').getAttribute('href')).toBe(
      `/cmdb/${OTHER}`,
    );
    expect(within(menu).getByText('Remove: runs on Server SRV-01')).toBeDefined();
    // Escape closes the menu and goes no further (a dialog or drawer around stays open).
    let escapes = 0;
    const outside = (event: KeyboardEvent) => {
      if (event.key === 'Escape') escapes += 1;
    };
    document.addEventListener('keydown', outside);
    try {
      fireEvent.keyDown(document.activeElement ?? menu, { key: 'Escape' });
    } finally {
      document.removeEventListener('keydown', outside);
    }
    await waitFor(() => {
      expect(screen.queryByTestId('ci-map-menu')).toBeNull();
    });
    expect(escapes).toBe(0);
    expect(screen.getByTestId('ci-map-canvas')).toBeDefined();
    expect(screen.getByTestId('ci-tabs')).toBeDefined();
  });

  it('refetches the map for a change on a shown CI only (one filtered list channel)', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const fake = api();
    window.history.pushState({}, '', `/cmdb/${CI}?tab=map`);
    render(<Shown />);
    await flowNode(OTHER);
    await waitFor(() => {
      expect(realtime.channels()).toContain('t:tenant:cmdb:all');
    });
    // Never one channel per node (condition 9).
    expect(realtime.channels().filter((c) => c.includes(OTHER))).toEqual([]);
    const path = `/api/v1/cmdb/cis/${CI}/neighbours`;
    const before = fake.find('GET', path).length;
    act(() => {
      realtime.publish(':cmdb:all', {
        type: 'cmdb.ci.changed',
        ids: ['a0000000-0000-7000-8000-0000000000ff'],
      });
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fake.find('GET', path).length).toBe(before);
    act(() => {
      realtime.publish(':cmdb:all', {
        type: 'cmdb.ci.changed',
        ids: [OTHER],
        fields: ['relationships'],
      });
    });
    await waitFor(() => {
      expect(fake.find('GET', path).length).toBeGreaterThan(before);
    });
  });
});

describe('CMDB › the Versions tab', () => {
  it('compares two versions grouped as attributes and relationships, in words', async () => {
    setDefaultClientFactory(inertClientFactory);
    api();
    window.history.pushState({}, '', `/cmdb/${CI}?tab=versions`);
    render(<Shown />);
    await screen.findByTestId('ci-version-3');
    // Pick the two versions (Ant Design selects, by keyboard).
    const pick = async (testId: string, label: RegExp) => {
      const select = screen.getByTestId(testId);
      fireEvent.mouseDown(select.querySelector('.ant-select-selector') ?? select);
      const options = await screen.findAllByText(label);
      const option = options.at(-1);
      if (option === undefined) throw new Error('no option');
      fireEvent.click(option);
    };
    await pick('ci-versions-from', /^Version 2,/);
    await pick('ci-versions-to', /^Version 3,/);
    fireEvent.click(screen.getByTestId('ci-versions-compare'));
    const attributes = await screen.findByTestId('ci-compare-attributes');
    const relationships = screen.getByTestId('ci-compare-relationships');
    // States by label; another record never by its ID; long text behind "Show all".
    expect(within(attributes).getByTestId('ci-compare-state_id').textContent).toContain('In use');
    expect(attributes.textContent).not.toContain(OTHER);
    expect(within(attributes).getByTestId('ci-compare-owner_user_id').textContent).toContain('Set');
    const toggle = within(attributes).getByTestId('long-text-toggle');
    expect(toggle.textContent).toBe('Show all');
    expect(within(attributes).getByTestId('ci-compare-description').textContent).not.toContain(
      'x'.repeat(400),
    );
    fireEvent.click(toggle);
    expect(within(attributes).getByTestId('ci-compare-description').textContent).toContain(
      'x'.repeat(400),
    );
    // Relationships: added to a CI the reader may not open, removed from one they may.
    expect(relationships.textContent).toContain("runs on A CI you can't open");
    expect(relationships.textContent).toContain('runs on Server SRV-01 (CI-2)');
    expect(relationships.textContent).toContain('Added');
    expect(relationships.textContent).toContain('Removed');
  });
});
