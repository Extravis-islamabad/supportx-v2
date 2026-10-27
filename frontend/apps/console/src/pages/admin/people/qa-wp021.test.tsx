import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { DepartmentOut, SiteOut, UserDetail } from '@supportx/api-client';
import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession, fakeUser, problem } from '../../../test/api';

// WP-021-FIX: one test per finding of ~/Desktop/qa-wp021/QA-REPORT.md (BUG-01..07, C1..C5; D-096).

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
type Routes = NonNullable<NonNullable<Parameters<typeof consoleApi>[0]>['routes']>;
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ANSWERED = { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 };

function site(id: string, name: string): SiteOut {
  return {
    id,
    name,
    description: null,
    region: null,
    time_zone: null,
    default_language: null,
    address: null,
    phone: null,
    email: null,
    is_default: false,
    disabled: false,
    member_ids: [],
    version: 1,
  };
}
function department(id: string, name: string, siteId: string | null): DepartmentOut {
  return {
    id,
    name,
    code: null,
    site_id: siteId,
    head_id: null,
    parent_id: null,
    description: null,
    disabled: false,
    version: 1,
  };
}
const SITES = [site('s-r', 'Riyadh'), site('s-j', 'Jeddah')];
const DEPARTMENTS = [department('d-f', 'Finance', 's-r')];
const BILAL: UserDetail = fakeUser({
  id: 'u-9',
  display_name: 'Bilal Saleh',
  first_name: 'Bilal',
  last_name: 'Saleh',
  email: 'bilal@demo.test',
  user_type: 'requester',
  job_title: 'Analyst',
  version: 4,
});

function routes(extra: Routes = {}) {
  return api({
    me: ADMIN,
    routes: {
      'GET /api/v1/access-settings': { body: ANSWERED },
      'GET /api/v1/users': {
        body: { items: [BILAL], has_more: false, next_cursor: null, estimated_total: 12 },
      },
      'GET /api/v1/organization/sites': { body: SITES },
      'GET /api/v1/organization/departments': { body: DEPARTMENTS },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/users/u-9': { body: BILAL, headers: { ETag: '"4"' } },
      ...extra,
    },
  });
}

afterEach(() => {
  restore();
  vi.restoreAllMocks();
});

/** Choose an option of an Ant Design select by its visible text. */
async function choose(testId: string, option: string) {
  const select = await screen.findByTestId(testId);
  const selector = select.querySelector('.ant-select-selector') ?? select;
  fireEvent.mouseDown(selector);
  const items = await waitFor(() => {
    const found = screen
      .getAllByText(option)
      .filter((node) => node.closest('.ant-select-item-option') !== null);
    if (found.length === 0) throw new Error(`no option ${option}`);
    return found;
  });
  const last = items[items.length - 1];
  if (last === undefined) throw new Error(`no option ${option}`);
  fireEvent.click(last);
}

describe('Admin › People (WP-021-FIX)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/users');
  });

  it('BUG-02: a too-long value names its limit at the field', async () => {
    routes({
      'POST /api/v1/users': {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'body.job_title',
              code: 'value_too_long',
              message_key: 'errors.field.value_too_long_max',
              params: { max_length: 200 },
            },
          ],
        }),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('people-add'));
    fireEvent.change(await screen.findByTestId('person-first-name'), { target: { value: 'Q' } });
    fireEvent.click(screen.getByTestId('person-can-sign-in'));
    fireEvent.click(screen.getByTestId('person-save'));
    expect(await screen.findByText('Use at most 200 characters.')).toBeDefined();
  });

  it('BUG-03: after "keep mine" the notice clears and the form shows what was stored', async () => {
    let current = BILAL;
    const fake = routes({
      'GET /api/v1/users/u-9': () => ({
        body: current,
        headers: { ETag: `"${String(current.version)}"` },
      }),
      'PATCH /api/v1/users/u-9/person': (call) => {
        if (call.headers.get('If-Match') === '"4"') {
          return {
            status: 409,
            body: problem(409, 'version_conflict', {
              params: {
                changed_by: 'Sara Admin',
                changed_fields: 'job_title',
                changed_at: '2026-10-27T10:00:00Z',
              },
            }),
          };
        }
        current = { ...current, last_name: 'Salih', display_name: 'Bilal Salih', version: 6 };
        return { body: current };
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Saleh'));
    const form = await screen.findByTestId('person-form');
    fireEvent.change(within(form).getByTestId('person-last-name'), { target: { value: 'Salih' } });
    // Saved elsewhere meanwhile (no live message reached this browser): the save gets a 409.
    current = { ...BILAL, job_title: 'Changed elsewhere', version: 5 };
    fireEvent.click(screen.getByTestId('person-save'));
    fireEvent.click(await screen.findByTestId('conflict-keep-mine'));
    await waitFor(() => {
      expect(
        within(screen.getByTestId('person-form')).getByLabelText<HTMLInputElement>('Job title')
          .value,
      ).toBe('Changed elsewhere');
    });
    expect(screen.queryByTestId('person-stale')).toBeNull();
    const patches = fake.find('PATCH', '/api/v1/users/u-9/person');
    // Saved on top of the latest version, sending only my field.
    expect(patches.map((p) => p.headers.get('If-Match'))).toEqual(['"4"', '"5"']);
    expect(patches[1]?.body).toEqual({ last_name: 'Salih' });
  });

  it("BUG-03: the drawer's own type or sign-in change is not someone else's save", async () => {
    let current = BILAL;
    routes({
      'GET /api/v1/users/u-9': () => ({
        body: current,
        headers: { ETag: `"${String(current.version)}"` },
      }),
      'PUT /api/v1/users/u-9/sign-in': () => {
        current = { ...current, can_sign_in: false, version: 5 };
        return { body: current };
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Saleh'));
    await screen.findByTestId('person-form');
    fireEvent.click(screen.getByTestId('person-sign-in'));
    await waitFor(() => {
      expect(screen.getByTestId('person-sign-in').getAttribute('aria-checked')).toBe('false');
    });
    expect(screen.queryByTestId('person-stale')).toBeNull();
  });

  it('BUG-05: phone numbers keep left-to-right order, also in Arabic', async () => {
    routes();
    render(<App />);
    fireEvent.click(await screen.findByTestId('people-add'));
    for (const label of ['Phone', 'Mobile']) {
      const input = await screen.findByLabelText<HTMLInputElement>(label);
      // An inline style: Ant Design's RTL stylesheet sets `direction: rtl` on inputs, which
      // overrides a `dir` attribute (that is why the number showed reversed).
      expect(input.style.direction).toBe('ltr');
    }
  });

  it('BUG-07: no option of the person form has a null value (no React warning)', async () => {
    const error = vi.spyOn(console, 'error');
    routes();
    render(<App />);
    fireEvent.click(await screen.findByTestId('people-add'));
    await screen.findByTestId('person-form');
    await choose('person-request-visibility', 'All requests of their site');
    expect(error.mock.calls.some((call) => String(call[0]).includes('should not be `null`'))).toBe(
      false,
    );
  });

  it('C2: the counter counts people', async () => {
    routes();
    render(<App />);
    expect((await screen.findByTestId('users-total')).textContent).toBe('12 people');
  });

  it('C3: saving a person says "Saved."', async () => {
    routes({
      'PATCH /api/v1/users/u-9/person': { body: { ...BILAL, job_title: 'Lead', version: 5 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Saleh'));
    const form = await screen.findByTestId('person-form');
    fireEvent.change(within(form).getByLabelText('Job title'), { target: { value: 'Lead' } });
    fireEvent.click(screen.getByTestId('person-save'));
    expect(await screen.findByText('Saved.')).toBeDefined();
  });

  it('C4 (D-096): a department suggests its site when the site is empty, never overwrites', async () => {
    routes();
    render(<App />);
    fireEvent.click(await screen.findByTestId('people-add'));
    await choose('person-department', 'Finance');
    await waitFor(() => {
      expect(within(screen.getByTestId('person-site')).getByText('Riyadh')).toBeDefined();
    });
    // A site chosen by hand stays when the department changes.
    await choose('person-site', 'Jeddah');
    await choose('person-department', 'Finance');
    expect(within(screen.getByTestId('person-site')).getByText('Jeddah')).toBeDefined();
  });

  it('C5: making someone a technician asks first (it takes a licence seat)', async () => {
    const fake = routes({
      'PUT /api/v1/users/u-9/type': { body: { ...BILAL, user_type: 'technician', version: 5 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Saleh'));
    await screen.findByTestId('person-form');
    fireEvent.click(within(screen.getByTestId('person-type')).getByText('Technician'));
    expect(await screen.findByText(/uses one technician licence seat/)).toBeDefined();
    expect(fake.find('PUT', '/api/v1/users/u-9/type')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Make technician' }));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/users/u-9/type')).toHaveLength(1);
    });
  });
});

describe('Admin › Organisation (WP-021-FIX)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/organization/departments');
  });

  it('BUG-01: an empty name says it is required, never a validator code', async () => {
    routes({
      'POST /api/v1/organization/departments': {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'body.name',
              code: 'required',
              message_key: 'errors.field.required',
              params: {},
            },
          ],
        }),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('departments-add'));
    fireEvent.click(await screen.findByTestId('unit-save'));
    expect(await screen.findByText('This field is required.')).toBeDefined();
    expect(screen.queryByText('String Type')).toBeNull();
  });

  it('C1: a department has one site, headed "Site"', async () => {
    routes();
    render(<App />);
    const table = await screen.findByTestId('departments-table');
    expect(within(table).getByText('Site')).toBeDefined();
    expect(within(table).queryByText('Sites served')).toBeNull();
    expect(await within(table).findByText('Riyadh')).toBeDefined();
  });
});

describe('New incident (WP-021-FIX)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents/new');
  });

  it('BUG-04: picking the requester fills their department and its site before saving', async () => {
    const rana = fakeUser({
      id: 'u-1',
      display_name: 'Rana Requester',
      email: 'rana@demo.test',
      user_type: 'requester',
      department_id: 'd-f',
      site_id: null,
    });
    routes({
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
      'GET /api/v1/users': { body: { items: [rana], has_more: false, next_cursor: null } },
      'GET /api/v1/users/u-1': { body: rana },
      [`GET /api/v1/incidents/${fakeIncident().id}`]: { body: fakeIncident() },
    });
    render(<App />);
    await choose('inc-requester', 'Rana Requester');
    await waitFor(() => {
      expect(within(screen.getByTestId('inc-department')).getByText('Finance')).toBeDefined();
    });
    expect(within(screen.getByTestId('inc-site')).getByText('Riyadh')).toBeDefined();
  });
});
