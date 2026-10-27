import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { PeopleImport, UserDetail } from '@supportx/api-client';

import { App } from '../../../App';
import { consoleApi, fakeSession, fakeUser, problem } from '../../../test/api';

// WP-021: Admin › People, the person drawer, imports, Admin › Organisation and the
// technician-visibility question (D-073).

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ANSWERED = {
  technician_scope: 'group',
  answered_at: '2026-10-27T08:00:00Z',
  version: 1,
};
const BILAL: UserDetail = fakeUser({
  id: 'u-9',
  display_name: 'Bilal Saleh',
  first_name: 'Bilal',
  last_name: 'Saleh',
  email: 'bilal@demo.test',
  user_type: 'requester',
  version: 4,
  updated_at: '2026-10-27T09:30:00Z',
});

function routes(extra: NonNullable<NonNullable<Parameters<typeof consoleApi>[0]>['routes']> = {}) {
  return api({
    me: ADMIN,
    routes: {
      'GET /api/v1/access-settings': { body: ANSWERED },
      'GET /api/v1/users': { body: { items: [BILAL], has_more: false, next_cursor: null } },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/organization/departments': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/users/u-9': { body: BILAL, headers: { ETag: '"4"' } },
      ...extra,
    },
  });
}

afterEach(() => {
  restore();
});

/** The OK button of the open confirmation (the trigger button has the same name). */
async function confirmButton(name: string): Promise<HTMLElement> {
  const popup = await waitFor(() => {
    const found = document.querySelector<HTMLElement>('.ant-popconfirm');
    if (found === null) throw new Error('no confirmation open');
    return found;
  });
  return within(popup).getByRole('button', { name });
}

describe('Admin › People', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/users');
  });

  it('adding someone who signs in without an email shows the problem at the field', async () => {
    const fake = routes({
      'POST /api/v1/users': {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'body.email',
              code: 'email_required_for_sign_in',
              message_key: 'errors.field.email_required_for_sign_in',
              params: {},
            },
          ],
        }),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('people-add'));
    fireEvent.change(await screen.findByTestId('person-first-name'), {
      target: { value: 'Noor' },
    });
    fireEvent.click(screen.getByTestId('person-save'));
    expect(await screen.findByText(/An email address is needed to sign in/)).toBeDefined();
    const [sent] = fake.find('POST', '/api/v1/users');
    expect(sent?.body).toMatchObject({
      first_name: 'Noor',
      can_sign_in: true,
      user_type: 'requester',
    });
  });

  it('an open person keeps its version: a save elsewhere is said, saving shows the conflict', async () => {
    let current = BILAL;
    const fake = routes({
      'GET /api/v1/users/u-9': () => ({
        body: current,
        headers: { ETag: `"${String(current.version)}"` },
      }),
      'PATCH /api/v1/users/u-9/person': {
        status: 409,
        body: problem(409, 'version_conflict', {
          params: {
            changed_by: 'Sara Admin',
            changed_fields: 'job_title',
            changed_at: '2026-10-27T10:00:00Z',
          },
        }),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Saleh'));
    const form = await screen.findByTestId('person-form');
    fireEvent.change(within(form).getByTestId('person-last-name'), { target: { value: 'Salih' } });
    // Someone else saves; the record refetches (live) with a new version.
    current = { ...BILAL, version: 5, job_title: 'Analyst', updated_at: '2026-10-27T10:00:00Z' };
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
      await Promise.resolve();
    });
    fireEvent.click(screen.getByTestId('person-save'));
    expect(await screen.findByTestId('conflict-who')).toBeDefined();
    const [patch] = fake.find('PATCH', '/api/v1/users/u-9/person');
    // The version the editor started from, never the newer one: no silent overwrite.
    expect(patch?.headers.get('If-Match')).toBe('"4"');
    expect(patch?.body).toEqual({ last_name: 'Salih' });
  });

  it('deactivating asks first and sends the version on screen', async () => {
    const fake = routes({
      'POST /api/v1/users/u-9/deactivate': { body: { ...BILAL, status: 'disabled', version: 5 } },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Saleh'));
    fireEvent.click(await screen.findByTestId('person-deactivate'));
    fireEvent.click(await confirmButton('Deactivate'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/users/u-9/deactivate')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/users/u-9/deactivate')[0]?.headers.get('If-Match')).toBe(
      '"4"',
    );
  });

  it('shows import progress and the rows that were not imported, in words', async () => {
    const job: PeopleImport = {
      id: 'imp-1',
      file_name: 'people.csv',
      file_format: 'csv',
      status: 'done',
      match_on: 'email',
      total: 3,
      processed: 3,
      created_count: 1,
      updated_count: 1,
      failed_count: 1,
      problems: [{ row: 3, field: 'site_id', code: 'site_not_found', detail: null }],
      failure: null,
      created_at: '2026-10-27T09:00:00Z',
      finished_at: '2026-10-27T09:00:05Z',
    };
    routes({ 'GET /api/v1/people-imports': { body: [job] } });
    render(<App />);
    fireEvent.click(await screen.findByTestId('people-import'));
    const item = await screen.findByTestId('people-import-imp-1');
    expect(within(item).getByTestId('people-import-status').textContent).toBe('Finished');
    expect(within(item).getByTestId('people-import-counts').textContent).toBe(
      '3 of 3 rows: 1 added, 1 updated, 1 not imported',
    );
    fireEvent.click(within(item).getByText('Show rows not imported'));
    expect(await within(item).findByText('Site')).toBeDefined();
    expect(within(item).queryByText('site_not_found')).toBeNull(); // never the code
  });
});

describe('Admin › Organisation', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/organization/sites');
  });

  it('removing a site in use says what uses it and suggests making it inactive', async () => {
    routes({
      'GET /api/v1/organization/sites': {
        body: [
          {
            id: 's-1',
            name: 'QA-Site',
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
            version: 2,
          },
        ],
      },
      'DELETE /api/v1/organization/sites/s-1': {
        status: 409,
        body: problem(409, 'site_in_use', { params: { people: 3 } }),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sites-remove-QA-Site'));
    fireEvent.click(await confirmButton('Remove'));
    expect(
      await screen.findByText('Still in use (people: 3). Make it inactive instead.'),
    ).toBeDefined();
  });
});

describe('technician visibility (D-073)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/');
  });

  it('asks in a banner, "their groups" preselected, and saves as the first answer', async () => {
    const fake = routes({
      'GET /api/v1/access-settings': {
        body: { technician_scope: 'group', answered_at: null, version: 0 },
      },
      'PUT /api/v1/access-settings': { body: ANSWERED },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('technician-scope-choose'));
    const question = await screen.findByTestId('technician-scope-question');
    expect(within(question).getByLabelText(/Their groups \(recommended\)/)).toHaveProperty(
      'checked',
      true,
    );
    fireEvent.click(screen.getByTestId('technician-scope-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/access-settings')).toHaveLength(1);
    });
    const [put] = fake.find('PUT', '/api/v1/access-settings');
    expect(put?.headers.get('If-Match')).toBe('"0"');
    expect(put?.body).toEqual({ technician_scope: 'group' });
  });

  it('is not asked of people who cannot manage roles', async () => {
    api({
      me: fakeSession({ roles: ['technician'] }),
      routes: {
        'GET /api/v1/access-settings': {
          body: { technician_scope: 'group', answered_at: null, version: 0 },
        },
      },
    });
    render(<App />);
    await screen.findByRole('main');
    expect(screen.queryByTestId('technician-scope-banner')).toBeNull();
  });
});
