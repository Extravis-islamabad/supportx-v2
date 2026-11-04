import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakePermissions, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-040 (D-041): the connector defaults card on Admin › Integrations.
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const SETTINGS = '/api/v1/integrations/connector-settings';
const CATALOGUE = '/api/v1/integrations/catalogue';
const grant = (key: string) => ({
  key,
  scope: 'all' as const,
  scopes: ['all' as const],
  conditional: false,
});
const DEFAULTS = { failing_after_runs: 3, error_retention_days: 90, sync_minutes: 30, version: 0 };

describe('Admin › Integrations › connector defaults', () => {
  afterEach(() => {
    restore();
    setDefaultClientFactory(inertClientFactory);
  });

  it('saves only with a change, sends the version read', async () => {
    window.history.pushState({}, '', '/admin/integrations');
    const fake = api({
      me: {
        ...fakeSession({ roles: ['tenant_admin', 'technician'] }),
        permissions: [...fakePermissions('tenant_admin'), grant('integrations.manage')],
      },
      routes: {
        [`GET ${CATALOGUE}`]: { body: [] },
        [`GET ${SETTINGS}`]: { body: DEFAULTS },
        [`PUT ${SETTINGS}`]: { body: { ...DEFAULTS, failing_after_runs: 1, version: 1 } },
      },
    });
    render(<App />);
    const save = await screen.findByTestId('connector-settings-save');
    expect(save.hasAttribute('disabled')).toBe(true); // nothing changed yet
    fireEvent.change(screen.getByTestId('connector-settings-failing_after_runs'), {
      target: { value: '1' },
    });
    expect(save.hasAttribute('disabled')).toBe(false);
    fireEvent.click(save);
    await waitFor(() => {
      expect(fake.find('PUT', SETTINGS)).toHaveLength(1);
    });
    const put = fake.find('PUT', SETTINGS)[0];
    expect(put?.body).toEqual({
      failing_after_runs: 1,
      error_retention_days: 90,
      sync_minutes: 30,
    });
    expect(put?.headers.get('if-match')).toBe('"0"');
  });

  it('is not shown without integrations.manage', async () => {
    window.history.pushState({}, '', '/admin/integrations');
    api({
      me: {
        ...fakeSession({ roles: ['technician'] }),
        permissions: [...fakePermissions('technician'), grant('integrations.view')],
      },
      routes: { [`GET ${CATALOGUE}`]: { body: [] }, [`GET ${SETTINGS}`]: { body: DEFAULTS } },
    });
    render(<App />);
    await screen.findByTestId('admin-integrations');
    expect(screen.queryByTestId('connector-settings')).toBeNull();
  });
});
