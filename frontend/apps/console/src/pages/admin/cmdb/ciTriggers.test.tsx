import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakePermissions, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-053 S5d (REQ-CMDB-023): Admin › CMDB lists triggers on configuration items. The editor is the
// incidents' one for the CI record type: the CI's events by label (the server's offer), in a record's life order, and
// only "set a field" (a CI has no notes); its list and offer are asked for the CI record type.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

// The fake admin's rights plus the CMDB's configure right (the page's own gate).
const ADMIN = fakeSession(
  { display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] },
  {
    permissions: [
      ...fakePermissions('tenant_admin'),
      { key: 'cmdb.configure', scope: 'all', scopes: ['all'], conditional: false },
    ],
  },
);
// downtime_started joins with its reader, after #608.
const CI_OFFER = [
  'created',
  'relationship_added',
  'relationship_removed',
  'status_changed',
  'updated',
];

function api() {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/cmdb/settings': { body: { exclude_eol_from_pickers: true, version: 1 } },
      'GET /api/v1/cmdb/ci-types': { body: { items: [] } },
      'GET /api/v1/cmdb/ci-states': { body: { items: [] } },
      'GET /api/v1/automation/triggers': { body: [] },
      'GET /api/v1/automation/trigger-events': {
        body: { offered: CI_OFFER, offered_actions: ['set'] },
      },
      'GET /api/v1/automation/fields': {
        body: [
          { name: 'state_id', kind: 'reference', values: null, settable: true, derived: false },
          {
            name: 'criticality',
            kind: 'code',
            values: ['high', 'low'],
            settable: true,
            derived: false,
          },
          { name: 'name', kind: 'text', values: null, settable: false, derived: false },
        ],
      },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('Admin › CMDB › Configuration item triggers (WP-053 S5d)', () => {
  it("offers the CI's events by label, in order, and only setting a field", async () => {
    setDefaultClientFactory(inertClientFactory);
    const fake = api();
    window.history.pushState({}, '', '/admin/cmdb');
    render(<App />);
    const block = await screen.findByTestId('cmdb-triggers');
    expect(block.textContent).toContain('Configuration item triggers');
    fireEvent.click(await within(block).findByTestId('trigger-add'));
    const events = await screen.findByTestId('trigger-events');
    await waitFor(() => {
      expect(within(events).getAllByRole('checkbox')).toHaveLength(5);
    });
    expect(events.textContent).toContain('When a relationship is added');
    const labels = within(events)
      .getAllByRole('checkbox')
      .map((box) => box.closest('label')?.textContent);
    expect(labels).toEqual([
      'When created',
      'When fields change',
      'When the status changes',
      'When a relationship is added',
      'When a relationship is removed',
    ]);
    expect(events.textContent).not.toContain('When a downtime starts');
    expect(events.textContent).not.toMatch(/trigger_event|_/);
    const kind = screen.getByTestId('trigger-action-0-kind');
    fireEvent.mouseDown(kind.querySelector('.ant-select-selector') ?? kind);
    await screen.findAllByText('Set a field');
    expect(
      screen
        .queryAllByText('Add a private note')
        .filter((n) => n.closest('.ant-select-item-option') !== null),
    ).toHaveLength(0);
    const asked = fake.find('GET', '/api/v1/automation/trigger-events');
    expect(asked[0]?.url.searchParams.get('record_type')).toBe('cmdb_ci');
    const listed = fake.find('GET', '/api/v1/automation/triggers');
    expect(listed[0]?.url.searchParams.get('record_type')).toBe('cmdb_ci');
  });
});
