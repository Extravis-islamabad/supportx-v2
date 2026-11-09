import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// Settings review 2026-11-06 (~/Desktop/supportx-daily/2026-11-06-settings-qa.md): incident
// settings. Each test is named after its finding.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});
const ADMIN = fakeSession({ roles: ['tenant_admin'] });

function open(path: string, routes: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/reply-templates': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      ...routes,
    },
  });
  restore = fake.restore;
  window.history.pushState({}, '', path);
  render(<App />);
  return fake;
}

const itemOf = (testId: string) => screen.getByTestId(testId).closest('.ant-form-item');

describe('QA6S incident settings', () => {
  it('QA6S-SVC-03: an empty reply template names each missing field, at the field', async () => {
    const fake = open('/admin/incidents/reply-templates');
    fireEvent.click(await screen.findByTestId('tpl-new'));
    fireEvent.click(await screen.findByTestId('tpl-save'));
    await waitFor(() => {
      expect(itemOf('tpl-name')?.className).toContain('ant-form-item-has-error');
    });
    expect(itemOf('tpl-name')?.textContent).toContain('This field is required.');
    expect(itemOf('tpl-name')?.querySelector('.ant-form-item-required')).not.toBeNull();
    // Nothing sent, and no unnamed list of messages under the editor.
    expect(fake.find('POST', '/api/v1/incidents/reply-templates')).toHaveLength(0);
    expect(screen.queryByText('This field is required. This field is required.')).toBeNull();
  });
});
