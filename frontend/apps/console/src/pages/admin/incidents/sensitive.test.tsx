import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { CustomField } from '@supportx/api-client';
import {
  fakeCustomField,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// Sensitive custom fields (WP-057 S3b-2b): the switch on its own route, never the editor's
// draft; turning it off asks for a reason and the field's name, and says what it affects.

let restore: () => void = () => undefined;
const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const SALARY: CustomField = fakeCustomField({
  id: 'cf-salary',
  key: 'salary_band',
  labels: { en: 'Salary band', ar: 'فئة الراتب' },
  in_use: true,
});
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
};
const SENSITIVITY = 'GET /api/v1/custom-fields/cf-salary/sensitivity';
const PUT = '/api/v1/custom-fields/cf-salary/sensitivity';

function open(field: CustomField, records: number) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      ...COMMON,
      'GET /api/v1/custom-fields': { body: [field] },
      [SENSITIVITY]: {
        body: {
          sensitive: field.sensitive,
          seal_state: field.seal_state,
          records,
          version: field.version,
        },
      },
      [`PUT ${PUT}`]: { body: { sensitive: false, seal_state: 'opening', records, version: 3 } },
    },
  });
  restore = fake.restore;
  window.history.pushState({}, '', '/admin/incidents/custom-fields');
  render(<App />);
  return fake;
}

async function editor() {
  fireEvent.click(await screen.findByTestId('cf-edit-salary_band'));
  fireEvent.click(await screen.findByText('For integrations and performance'));
  return screen.findByTestId('cf-sensitive');
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
  vi.restoreAllMocks();
});

describe('Admin › Incidents › Custom fields › Sensitive', () => {
  it('turning it on saves at once on its own route', async () => {
    const fake = open(SALARY, 4);
    await editor();
    fireEvent.click(screen.getByTestId('cf-sensitive-switch'));
    await waitFor(() => {
      expect(fake.find('PUT', PUT)).toHaveLength(1);
    });
    expect(fake.find('PUT', PUT)[0]?.body).toEqual({
      sensitive: true,
      reason: null,
      confirm_name: null,
    });
    expect(fake.find('PUT', PUT)[0]?.headers.get('If-Match')).toBe('"1"');
    expect(fake.find('PATCH', '/api/v1/custom-fields/cf-salary')).toHaveLength(0);
  });

  it('turning it off needs a reason and the name, and says what it affects', async () => {
    const sealed = { ...SALARY, sensitive: true, seal_state: 'sealed' as const, version: 2 };
    const fake = open(sealed, 4);
    await editor();
    expect(screen.getByTestId('cf-editor-seal-state').textContent).toBe('Sealed');
    expect(screen.getByTestId('cf-seal-salary_band').textContent).toBe('Sealed');
    fireEvent.click(screen.getByTestId('cf-sensitive-switch'));
    const dialog = await screen.findByTestId('cf-sensitive-off');
    await waitFor(() => {
      expect(within(dialog).getByTestId('cf-sensitive-off-impact').textContent).toBe(
        "4 records' values will be stored readable again.",
      );
    });
    expect(dialog.textContent).toContain('Existing exports and backups are not changed.');
    const ok = screen.getByTestId('cf-sensitive-off-ok');
    expect(ok.hasAttribute('disabled')).toBe(true);
    fireEvent.change(screen.getByTestId('cf-sensitive-off-reason'), {
      target: { value: 'No longer personal data' },
    });
    fireEvent.change(screen.getByTestId('cf-sensitive-off-confirm'), {
      target: { value: 'salary' },
    });
    expect(ok.hasAttribute('disabled')).toBe(true); // not the name yet
    fireEvent.change(screen.getByTestId('cf-sensitive-off-confirm'), {
      target: { value: 'salary band ' },
    });
    expect(ok.hasAttribute('disabled')).toBe(false);
    fireEvent.click(ok);
    await waitFor(() => {
      expect(fake.find('PUT', PUT)).toHaveLength(1);
    });
    expect(fake.find('PUT', PUT)[0]?.body).toEqual({
      sensitive: false,
      reason: 'No longer personal data',
      confirm_name: 'salary band',
    });
  });

  it('shows the job running in words while values are being sealed', async () => {
    open({ ...SALARY, sensitive: true, seal_state: 'sealing' }, 4);
    await editor();
    expect(screen.getByTestId('cf-editor-seal-state').textContent).toBe('Sealing values…');
    expect(screen.getByTestId('cf-sensitive-moving').textContent).toContain(
      'lists cannot be filtered by this field',
    );
  });
});
