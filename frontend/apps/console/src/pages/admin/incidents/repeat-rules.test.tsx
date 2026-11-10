import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, fakeEntitlements } from '../../../test/api';

// WP-044c D16 (REQ-PRB-068): Admin › Incidents › Repeated incidents.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});
const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const DEFAULT = {
  id: '01a1a2b3-0000-7000-8000-0000000bb001',
  name: 'Same category and site',
  match: 'category_site',
  threshold: 10,
  window_hours: 24,
  notify_group_id: null,
  enabled: true,
  is_default: true,
  version: 1,
};

function open(routes: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/problem-repeats/rules': { body: [DEFAULT] },
      ...routes,
    },
  });
  restore = fake.restore;
  window.history.pushState({}, '', '/admin/incidents/repeat-rules');
  render(<App />);
  return fake;
}

describe('Repeated incidents (D16)', () => {
  it('REQ-PRB-068: the default rule in words, and a new one is added', async () => {
    const fake = open({ 'POST /api/v1/problem-repeats/rules': { status: 201, body: DEFAULT } });
    const table = await screen.findByTestId('repeat-rules');
    await waitFor(() => {
      expect(table.textContent).toContain('Same category and site');
    });
    expect(table.textContent).toContain(
      '10 or more incidents in The same category and site within 24 h',
    );
    fireEvent.click(screen.getByTestId('repeat-rule-add'));
    fireEvent.change(await screen.findByTestId('repeat-rule-name'), {
      target: { value: 'Printers' },
    });
    fireEvent.click(within(screen.getByTestId('repeat-rule-editor')).getByText('Save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/problem-repeats/rules')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/problem-repeats/rules')[0]?.body).toMatchObject({
      name: 'Printers',
      match: 'category_site',
      threshold: 10,
      window_hours: 24,
      enabled: true,
    });
    // The default rule can only be switched off.
    expect(screen.queryByTestId(`repeat-rule-remove-${DEFAULT.id}`)).toBeNull();
  });

  it('D-140 item 5: without problems (Essentials) it is locked with the upgrade hint', async () => {
    const essentials = fakeEntitlements({
      edition: 'essentials',
      features: ['incident', 'service_request', 'knowledge', 'sla', 'ai_assist'],
    });
    const fake = open({ 'GET /api/v1/entitlements': { body: essentials } });
    expect((await screen.findByTestId('repeat-rules-locked')).textContent).toContain(
      'Not included in your plan',
    );
    expect(fake.find('GET', '/api/v1/problem-repeats/rules')).toHaveLength(0);
  });
});
