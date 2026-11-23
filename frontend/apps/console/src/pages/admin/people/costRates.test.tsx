import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { CostRate, CostRates, UserDetail } from '@supportx/api-client';
import { fakePermissions } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession, fakeUser, problem } from '../../../test/api';

// A person's cost per hour (REQ-INC-068): the "Cost per hour" tab of the person drawer, only
// for people with users.view_cost_rates, editable with users.manage_cost_rates.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});
const CHANNEL = 't:demo:queue:user_cost_rates';

const BILAL: UserDetail = fakeUser({
  id: 'u-9',
  display_name: 'Bilal Saleh',
  first_name: 'Bilal',
  last_name: 'Saleh',
  user_type: 'technician',
  version: 4,
});

function rate(overrides: Partial<CostRate>): CostRate {
  return {
    id: 'r-1',
    user_id: 'u-9',
    rate: '40.00',
    currency: 'USD',
    effective_from: '2026-10-01T00:00:00Z',
    state: 'current',
    created_at: '2026-10-01T00:00:00Z',
    created_by: null,
    updated_at: '2026-10-01T00:00:00Z',
    version: 1,
    ...overrides,
  };
}

const CURRENT = rate({});
const UPCOMING = rate({
  id: 'r-2',
  rate: '45.50',
  effective_from: '2027-01-01T00:00:00Z',
  state: 'future',
});
const OLD = rate({
  id: 'r-0',
  rate: '35.00',
  effective_from: '2026-01-01T00:00:00Z',
  state: 'past',
});
const RATES: CostRates = {
  user_id: 'u-9',
  currency: 'USD',
  current: CURRENT,
  items: [UPCOMING, CURRENT, OLD],
};

function session(keys: string[]) {
  const admin = fakePermissions('tenant_admin');
  return fakeSession(
    { display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] },
    {
      permissions: [
        ...admin,
        ...keys.map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      ],
    },
  );
}

function routes(
  keys: string[],
  extra: NonNullable<Parameters<typeof consoleApi>[0]>['routes'] = {},
) {
  const fake = consoleApi({
    me: session(keys),
    routes: {
      'GET /api/v1/access-settings': {
        body: { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 },
      },
      'GET /api/v1/users': { body: { items: [BILAL], has_more: false, next_cursor: null } },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/organization/departments': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/users/u-9': { body: BILAL, headers: { ETag: '"4"' } },
      'GET /api/v1/users/u-9/cost-rates': { body: RATES },
      'GET /api/v1/realtime/lists/user_cost_rates': { body: { channels: [CHANNEL] } },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

async function openCostTab() {
  render(<App />);
  fireEvent.click(await screen.findByText('Bilal Saleh'));
  const drawer = await screen.findByTestId('person-drawer');
  fireEvent.click(await within(drawer).findByRole('tab', { name: 'Cost per hour' }));
  return screen.findByTestId('cost-rates-card');
}

describe('Admin › People › Cost per hour', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/users');
  });

  it('is not there without users.view_cost_rates, and the rates are never asked for', async () => {
    const fake = routes([]);
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Saleh'));
    const drawer = await screen.findByTestId('person-drawer');
    await within(drawer).findByRole('tab', { name: 'Details' });
    expect(within(drawer).queryByRole('tab', { name: 'Cost per hour' })).toBeNull();
    expect(fake.find('GET', '/api/v1/users/u-9/cost-rates')).toHaveLength(0);
  });

  it('viewing alone shows the current rate and the history, with no way to change them', async () => {
    routes(['users.view_cost_rates']);
    const card = await openCostTab();
    const current = await within(card).findByTestId('cost-rate-current');
    expect(current.textContent).toContain('$40.00');
    const table = within(card).getByTestId('cost-rates-table');
    expect(within(table).getAllByRole('row')).toHaveLength(4); // header + three rates
    expect(within(table).getByTestId('cost-rate-state-r-2').textContent).toBe('Upcoming');
    expect(within(table).getByTestId('cost-rate-state-r-1').textContent).toBe('In force');
    expect(within(table).getByTestId('cost-rate-state-r-0').textContent).toBe('Earlier');
    expect(within(card).queryByTestId('cost-rate-add')).toBeNull();
    expect(within(card).queryByTestId('cost-rate-change-r-1')).toBeNull();
  });

  it('managing sets a new rate with an effective moment and an idempotency key', async () => {
    const fake = routes(['users.view_cost_rates', 'users.manage_cost_rates'], {
      'POST /api/v1/users/u-9/cost-rates': {
        status: 201,
        body: rate({ id: 'r-3', rate: '50.00' }),
      },
    });
    const card = await openCostTab();
    fireEvent.click(await within(card).findByTestId('cost-rate-add'));
    const dialog = await screen.findByTestId('cost-rate-dialog');
    fireEvent.change(within(dialog).getByTestId('cost-rate-amount'), { target: { value: '50' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/users/u-9/cost-rates')).toHaveLength(1);
    });
    const [post] = fake.find('POST', '/api/v1/users/u-9/cost-rates');
    expect(post?.headers.get('Idempotency-Key')).toBeTruthy();
    const body = post?.body as { rate: string; effective_from: string };
    expect(Number(body.rate)).toBe(50);
    expect(Number.isNaN(Date.parse(body.effective_from))).toBe(false);
  });

  it('a superseded rate offers no change; a refused change says why in words', async () => {
    const fake = routes(['users.view_cost_rates', 'users.manage_cost_rates'], {
      'PATCH /api/v1/users/u-9/cost-rates/r-1': {
        status: 409,
        body: problem(409, 'cost_rate_superseded'),
      },
    });
    const card = await openCostTab();
    expect(within(card).queryByTestId('cost-rate-change-r-0')).toBeNull();
    fireEvent.click(await within(card).findByTestId('cost-rate-change-r-1'));
    const dialog = await screen.findByTestId('cost-rate-dialog');
    fireEvent.change(within(dialog).getByTestId('cost-rate-amount'), { target: { value: '41' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/users/u-9/cost-rates/r-1')).toHaveLength(1);
    });
    const [patch] = fake.find('PATCH', '/api/v1/users/u-9/cost-rates/r-1');
    expect(patch?.headers.get('If-Match')).toBe('"1"');
    expect(await within(dialog).findByRole('alert')).toBeDefined();
    expect(dialog.textContent).toContain('A later rate is already in force');
    expect(dialog.textContent).not.toContain('cost_rate_superseded');
  });

  it("refetches live when this person's rates change elsewhere (the message names the person)", async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const fake = routes(['users.view_cost_rates']);
    await openCostTab();
    await waitFor(() => {
      expect(realtime.channels()).toContain(CHANNEL);
    });
    const before = fake.find('GET', '/api/v1/users/u-9/cost-rates').length;
    act(() => {
      realtime.publish(CHANNEL, { type: 'user_cost_rates.changed', ids: ['someone-else'] });
    });
    act(() => {
      realtime.publish(CHANNEL, { type: 'user_cost_rates.changed', ids: ['u-9'] });
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/users/u-9/cost-rates').length).toBe(before + 1);
    });
  });
});
