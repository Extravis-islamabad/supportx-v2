import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { CustomField, RoleDetail, RoleSummary } from '@supportx/api-client';
import {
  fakeCustomField,
  fakeFileRules,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi, problem } from '../../test/api';

// WP-026 QA findings (~/Desktop/qa-wp026/QA-REPORT.md; WP-026-FIX, D-091). Each test is named
// after its finding and failed before the fix.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ roles: ['tenant_admin'] });
// The files screen needs a staff member (tenant admin who is also a technician).
const STAFF_ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });
const ADMIN_AR = fakeSession({ roles: ['tenant_admin'], locale: 'ar' });

const TAG: CustomField = fakeCustomField({
  id: 'cf-tag',
  key: 'asset_tag',
  labels: { en: 'Asset tag' },
  changed_by: 'Amal Admin',
  changed_at: '2026-10-27T09:00:00Z',
  version: 1,
});
const COST: CustomField = fakeCustomField({
  id: 'cf-cost',
  key: 'cost',
  field_type: 'decimal',
  labels: { en: 'Cost' },
  validation: {
    required: false,
    min: '0',
    max: '1000.5',
    min_length: null,
    max_length: null,
    pattern: null,
  },
  sort_order: 1,
});
const FLOOR: CustomField = fakeCustomField({
  id: 'cf-floor',
  key: 'floor',
  field_type: 'choice',
  labels: { en: 'Floor', ar: 'الطابق' },
  choices: [
    { code: 'ground', labels: { en: 'Ground', ar: 'أرضي' }, retired: false },
    { code: 'first', labels: { en: 'First' }, retired: false },
  ],
  index_state: 'active',
  sort_order: 2,
});
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  'GET /api/v1/custom-fields': { body: [TAG, COST, FLOOR] },
};
const conflict = (changedBy: string, fields: string) => ({
  status: 409,
  body: problem(409, 'version_conflict', {
    params: {
      expected_version: 1,
      current_version: 2,
      changed_by: changedBy,
      changed_fields: fields,
      changed_at: '2026-10-27T09:05:00Z',
    },
  }),
});

function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}

function open(path: string) {
  window.history.pushState({}, '', path);
  render(<App />);
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
  vi.restoreAllMocks();
});

describe('WP-026 QA findings', () => {
  it('BUG-01: an open editor keeps its version, says who saved meanwhile, and a save asks', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let fields = [TAG];
    const fake = api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'GET /api/v1/custom-fields': () => ({ body: fields }),
        'PATCH /api/v1/custom-fields/cf-tag': (call) =>
          call.headers.get('If-Match') === '"1"'
            ? conflict('Basim Admin', 'labels')
            : { body: { ...TAG, version: 3 } },
      },
    });
    open('/admin/incidents/custom-fields');
    fireEvent.click(await screen.findByTestId('cf-edit-asset_tag'));
    fireEvent.change(await screen.findByTestId('cf-help-en'), {
      target: { value: 'Mine: the tag on the device' },
    });
    // Another admin renames the field: said at once, my typing stays.
    fields = [
      { ...TAG, labels: { en: 'Asset tag (theirs)' }, version: 2, changed_by: 'Basim Admin' },
    ];
    act(() => {
      realtime.publish(':broadcast', { type: 'metadata.custom_fields_changed', ids: [] });
    });
    expect((await screen.findByTestId('cf-changed-by')).textContent).toContain('Basim Admin');
    expect(screen.getByTestId<HTMLInputElement>('cf-help-en').value).toBe(
      'Mine: the tag on the device',
    );
    // Saving sends the version the editor started from: refused, with the conflict dialog.
    fireEvent.click(screen.getByTestId('cf-save'));
    expect((await screen.findByTestId('conflict-who')).textContent).toContain('Basim Admin');
    expect(fake.find('PATCH', '/api/v1/custom-fields/cf-tag')[0]?.headers.get('If-Match')).toBe(
      '"1"',
    );
    // Keep mine: saved knowingly over theirs, with their version.
    fireEvent.click(screen.getByTestId('conflict-keep-mine'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/custom-fields/cf-tag')).toHaveLength(2);
    });
    expect(fake.find('PATCH', '/api/v1/custom-fields/cf-tag')[1]?.headers.get('If-Match')).toBe(
      '"2"',
    );
  });

  it('BUG-01: incident settings drafts and dialogs save from their own version', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let version = 1;
    const fake = api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/settings': () => ({ body: { ...fakeIncidentCatalogue(), version } }),
        'PATCH /api/v1/incidents/settings/lists/level/values/tier_1': conflict(
          'Basim Admin',
          'levels',
        ),
      },
    });
    open('/admin/incidents/levels');
    fireEvent.click(await screen.findByTestId('list-level-edit-tier_1'));
    // The catalogue changes elsewhere while the dialog is open.
    version = 2;
    act(() => {
      realtime.publish(':broadcast', { type: 'work_items.settings_changed', ids: [] });
    });
    await new Promise((resolve) => setTimeout(resolve, 300));
    const dialog = await screen.findByTestId('list-level-dialog');
    const shipped = within(dialog).queryByTestId('list-level-dialog-shipped');
    if (shipped !== null) fireEvent.click(shipped);
    fireEvent.change(await screen.findByTestId('list-level-dialog-name-en'), {
      target: { value: 'First line' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(
        fake.find('PATCH', '/api/v1/incidents/settings/lists/level/values/tier_1'),
      ).toHaveLength(1);
    });
    expect(
      fake
        .find('PATCH', '/api/v1/incidents/settings/lists/level/values/tier_1')[0]
        ?.headers.get('If-Match'),
    ).toBe('"1"');
  });

  it('BUG-01: the file rules form keeps what was typed and saves from its version', async () => {
    const rules = fakeFileRules({ version: 1 });
    const fake = api({
      me: STAFF_ADMIN,
      routes: {
        'GET /api/v1/files/settings/rules': () => ({ body: rules }),
        'GET /api/v1/files/settings/usage': {
          body: { bytes_used: 12_500_000_000, files: 340, limit_bytes: 50_000_000_000 },
        },
        'PUT /api/v1/files/settings/rules': conflict('Basim Admin', 'max_file_mb'),
      },
    });
    open('/admin/files');
    // The form is filled once the saved rules arrive (a new form for each saved version).
    await waitFor(() => {
      expect(
        screen.getByRole<HTMLInputElement>('spinbutton', { name: 'Largest file (MB)' }).value,
      ).toBe('25');
    });
    const size = screen.getByRole<HTMLInputElement>('spinbutton', { name: 'Largest file (MB)' });
    fireEvent.change(size, { target: { value: '40' } });
    // Someone else saved meanwhile: this save is refused (409), never applied over theirs.
    fireEvent.click(screen.getByTestId('files-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/files/settings/rules')).toHaveLength(1);
    });
    expect(fake.find('PUT', '/api/v1/files/settings/rules')[0]?.headers.get('If-Match')).toBe(
      '"1"',
    );
    expect(await screen.findByText(/Someone else changed these settings/)).toBeDefined();
    expect(size.value).toBe('40'); // what was typed stays
  });

  it('BUG-01: the role editor saves from the version it opened with', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const hr: RoleSummary = {
      id: 'r-hr',
      key: 'hr_desk',
      name: 'HR desk',
      description: null,
      is_system: false,
      user_count: 0,
      version: 1,
    };
    let detail: RoleDetail = { ...hr, permissions: [] };
    const fake = api({
      me: fakeSession({ roles: ['tenant_admin', 'technician'] }),
      routes: {
        'GET /api/v1/permissions': { body: [] },
        'GET /api/v1/roles': () => ({ body: [{ ...hr, version: detail.version }] }),
        'GET /api/v1/roles/r-hr': () => ({ body: detail }),
        'GET /api/v1/realtime/lists/roles': { body: { channels: ['t:x:roles'] } },
        'PATCH /api/v1/roles/r-hr': conflict('Basim Admin', 'name'),
      },
    });
    open('/admin/roles');
    fireEvent.click(await screen.findByText('HR desk'));
    fireEvent.change(await screen.findByTestId('role-name'), { target: { value: 'HR team' } });
    detail = { ...detail, name: 'People desk', version: 2 };
    act(() => {
      realtime.publish(':roles', { type: 'identity_access.role_changed', ids: ['r-hr'] });
    });
    expect(await screen.findByTestId('role-stale')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/roles/r-hr')).toHaveLength(1);
    });
    expect(fake.find('PATCH', '/api/v1/roles/r-hr')[0]?.headers.get('If-Match')).toBe('"1"');
  });

  it('BUG-03: a typed number is never clamped or rounded; the limit is said', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/incidents/new');
    const cost = await screen.findByTestId<HTMLInputElement>('inc-custom-cost');
    fireEvent.change(cost, { target: { value: '5000' } });
    fireEvent.blur(cost);
    expect(cost.value).toBe('5000');
    // A long text is not cut: the counter turns up instead.
    const tag = screen.getByTestId<HTMLInputElement>('inc-custom-asset_tag');
    fireEvent.change(tag, { target: { value: 'x'.repeat(260) } });
    expect(tag.value).toHaveLength(260);
    expect(screen.getByText('260 / 250')).toBeDefined();
  });

  it('BUG-03: admin numbers are refused with the limit, not changed', async () => {
    api({
      me: STAFF_ADMIN,
      routes: {
        'GET /api/v1/files/settings/rules': { body: fakeFileRules({ version: 1 }) },
        'GET /api/v1/files/settings/usage': {
          body: { bytes_used: 12_500_000_000, files: 340, limit_bytes: 50_000_000_000 },
        },
      },
    });
    open('/admin/files');
    // The form is filled once the saved rules arrive (a new form for each saved version).
    await waitFor(() => {
      expect(
        screen.getByRole<HTMLInputElement>('spinbutton', { name: 'Largest file (MB)' }).value,
      ).toBe('25');
    });
    const size = screen.getByRole<HTMLInputElement>('spinbutton', { name: 'Largest file (MB)' });
    fireEvent.change(size, { target: { value: '500' } });
    fireEvent.blur(size);
    expect(size.value).toBe('500');
    fireEvent.click(screen.getByTestId('files-save'));
    expect(await screen.findByText('Maximum is 100.')).toBeDefined();
  });

  it('BUG-03: the next incident number is never rounded; 4.5 is refused', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/general');
    const next = await screen.findByTestId('settings-next-number');
    const input = next instanceof HTMLInputElement ? next : next.querySelector('input');
    if (input === null) throw new Error('no number input');
    fireEvent.change(input, { target: { value: '4.5' } });
    fireEvent.blur(input);
    expect(input.value).toBe('4.5');
    expect((await screen.findByTestId('settings-numbering-error-next_number')).textContent).toBe(
      'Enter a whole number.',
    );
  });

  it('BUG-04 + BUG-08: problems show at their fields and go away when the field is edited', async () => {
    api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'POST /api/v1/custom-fields': {
          status: 422,
          body: {
            ...problem(422, 'validation_failed'),
            errors: [
              {
                field: 'body.labels',
                code: 'english_label_required',
                message_key: 'errors.field.english_label_required',
                params: {},
              },
              {
                field: 'body.validation.max',
                code: 'invalid_value',
                message_key: 'errors.field.invalid_value',
                params: {},
              },
            ],
          },
        },
      },
    });
    open('/admin/incidents/custom-fields');
    fireEvent.click(await screen.findByTestId('cf-new'));
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('cf-type')));
    fireEvent.click(
      (
        await screen.findAllByText('Decimal number', {
          selector: '.ant-select-item-option-content',
        })
      )[0] as Element,
    );
    fireEvent.click(screen.getByTestId('cf-save'));
    expect((await screen.findByTestId('cf-error-labels')).textContent).toBe(
      'An English name is required.',
    );
    const max = screen.getByTestId('cf-max');
    expect(max.closest('.ant-form-item')?.textContent).toContain('This value is not valid');
    expect(screen.queryByTestId('cf-editor-problems')).toBeNull(); // nothing left at the top
    fireEvent.change(screen.getByTestId('cf-label-en'), { target: { value: 'Cost' } });
    expect(screen.queryByTestId('cf-error-labels')).toBeNull();
  });

  it('BUG-07: the "Indexed" tag uses a readable tone tag', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/custom-fields');
    const tag = await screen.findByTestId('cf-index-floor');
    expect(tag.getAttribute('data-tone')).toBe('success');
    expect(tag.textContent).toBe('Indexed');
  });

  it('C1 + C2 + C4: Enter adds a choice; columns named; choices reorder; names isolated', async () => {
    const fake = api({
      me: ADMIN,
      routes: { ...COMMON, 'PATCH /api/v1/custom-fields/cf-floor': { body: FLOOR } },
    });
    open('/admin/incidents/custom-fields');
    fireEvent.click(await screen.findByTestId('cf-edit-floor'));
    expect((await screen.findByTestId('cf-choice-columns')).textContent).toContain(
      'Name in Arabic',
    );
    fireEvent.click(screen.getByTestId('cf-choice-add'));
    const name = await screen.findByTestId('cf-choice-name-en');
    fireEvent.change(name, { target: { value: 'Second' } });
    fireEvent.keyDown(name, { key: 'Enter' });
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>('cf-choice-en-2').value).toBe('Second');
    });
    fireEvent.click(screen.getByTestId('cf-choice-up-1'));
    expect(screen.getByTestId<HTMLInputElement>('cf-choice-en-0').value).toBe('First');
    const offered = screen.getByTestId('cf-choices-offered');
    expect(offered.querySelectorAll('bdi')).toHaveLength(3);
    fireEvent.click(screen.getByTestId('cf-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/custom-fields/cf-floor')).toHaveLength(1);
    });
    const body = fake.find('PATCH', '/api/v1/custom-fields/cf-floor')[0]?.body as {
      choices: { code: string | null }[];
    };
    expect(body.choices.map((c) => c.code)).toEqual(['first', 'ground', null]);
  });

  it('C5: a retired field reads "(موقوف)" in Arabic', async () => {
    const item = fakeIncident({ custom: { floor: 'ground' } });
    api({
      me: ADMIN_AR,
      routes: {
        ...COMMON,
        'GET /api/v1/custom-fields': { body: [{ ...FLOOR, retired: true }] },
        [`GET /api/v1/incidents/${item.id}`]: { body: item },
      },
    });
    localStorage.setItem(
      `supportx.incident-tab.${fakeSession().user.id}`,
      JSON.stringify('details'),
    );
    open(`/incidents/${item.id}`);
    const tabs = await screen.findAllByRole('tab');
    fireEvent.click(tabs[1] as Element);
    expect((await screen.findByText(/الطابق \(موقوف\)/)).textContent).toBe('الطابق (موقوف)');
  });

  it('C6: when editing, the type is plain text, not a disabled control', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/custom-fields');
    fireEvent.click(await screen.findByTestId('cf-edit-cost'));
    expect((await screen.findByTestId('cf-type-fixed')).textContent).toBe('Decimal number');
    expect(screen.queryByTestId('cf-type')).toBeNull();
  });

  it('D-091 (O5): retired fields stay in the list filter under their own heading', async () => {
    api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'GET /api/v1/custom-fields': {
          body: [
            FLOOR,
            {
              ...FLOOR,
              id: 'cf-old',
              key: 'old_floor',
              labels: { en: 'Old floor' },
              retired: true,
            },
          ],
        },
        'GET /api/v1/incidents': {
          body: { items: [], has_more: false, next_cursor: null, people: {}, estimated_total: 0 },
        },
        'GET /api/v1/incidents/views': { body: [] },
        'GET /api/v1/incidents/counters': { body: [] },
      },
    });
    open('/incidents');
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-filter-custom-field')));
    const group = await screen.findByText('Retired fields', {
      selector: '.ant-select-item-group',
    });
    expect(group).toBeDefined();
    const options = [...document.querySelectorAll('.ant-select-item')].map((e) => e.textContent);
    expect(options).toEqual(['Floor', 'Retired fields', 'Old floor']);
  });
});
