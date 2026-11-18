import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { LegalHold, PersonUpload, UserDetail } from '@supportx/api-client';
import { fakePermissions } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi, fakeSession, fakeUser } from '../../../test/api';

// PersonDrawer › Privacy (ADR-052): the legal hold and the request's files to keep, over a
// mocked API only. No hold is placed and no erasure runs anywhere.

function Shown() {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App />
    </ConfigProvider>
  );
}

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const NOOR: UserDetail = fakeUser({
  id: 'u-7',
  display_name: 'Noor Hassan',
  first_name: 'Noor',
  last_name: 'Hassan',
  user_type: 'requester',
  version: 3,
});
const HINA: UserDetail = fakeUser({ id: 'u-admin-2', display_name: 'Hina Admin' });

const HELD: LegalHold = {
  user_id: 'u-7',
  held: true,
  held_at: '2026-11-15T09:00:00Z',
  held_by: 'u-admin-2',
  reason: 'Tribunal case 42',
  version: 3,
};
const FREE: LegalHold = { ...HELD, held: false, held_at: null, held_by: null, reason: null };

const UPLOADS: PersonUpload[] = [
  {
    id: 'f-1',
    name: 'contract.pdf',
    size: 2048,
    content_type: 'application/pdf',
    created_at: '2026-10-01T09:00:00Z',
    attached_to: 'work_item',
  },
  {
    id: 'f-2',
    name: 'photo.jpg',
    size: 1024,
    content_type: 'image/jpeg',
    created_at: '2026-10-02T09:00:00Z',
    attached_to: null,
  },
];

function session(keys: string[]) {
  return fakeSession(
    { display_name: 'Tariq Technician', roles: ['technician'] },
    {
      permissions: [
        ...fakePermissions('technician'),
        ...['users.view', 'users.manage', ...keys].map((key) => ({
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
  hold: LegalHold,
  extra: NonNullable<Parameters<typeof consoleApi>[0]>['routes'] = {},
) {
  const fake = consoleApi({
    me: session(keys),
    routes: {
      'GET /api/v1/access-settings': {
        body: { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 },
      },
      'GET /api/v1/users': { body: { items: [NOOR, HINA], has_more: false, next_cursor: null } },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/organization/departments': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/users/u-7': { body: NOOR, headers: { ETag: '"3"' } },
      'GET /api/v1/users/u-admin-2': { body: HINA },
      'GET /api/v1/people/u-7/legal-hold': { body: hold, headers: { ETag: '"3"' } },
      'GET /api/v1/people/u-7/uploads': { body: { items: UPLOADS, next_cursor: null } },
      'GET /api/v1/erasures': { body: { items: [] } },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

async function pick(testId: string, title: string) {
  const select = (await screen.findByTestId(testId)).querySelector('.ant-select-selector');
  if (select === null) throw new Error('not an Ant Design Select');
  fireEvent.mouseDown(select);
  const options = () =>
    Array.from(document.querySelectorAll('.ant-select-item-option')).find((el) =>
      el.textContent.includes(title),
    );
  await waitFor(() => {
    expect(options()).toBeDefined();
  });
  const option = options();
  if (option === undefined) throw new Error('no such option');
  fireEvent.click(option);
}

async function openPrivacy() {
  render(<Shown />);
  fireEvent.click(await screen.findByText('Noor Hassan'));
  const drawer = await screen.findByTestId('person-drawer');
  fireEvent.click(await within(drawer).findByRole('tab', { name: 'Privacy' }));
  return drawer;
}

describe('PersonDrawer › Privacy › Legal hold', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/users');
  });

  it('is not there without the holds or erase right', async () => {
    const fake = routes([], HELD);
    render(<Shown />);
    fireEvent.click(await screen.findByText('Noor Hassan'));
    const drawer = await screen.findByTestId('person-drawer');
    await within(drawer).findByRole('tab', { name: 'Details' });
    expect(within(drawer).queryByRole('tab', { name: 'Privacy' })).toBeNull();
    expect(fake.find('GET', '/api/v1/people/u-7/legal-hold')).toHaveLength(0);
  });

  it('with the erase right alone it shows who placed it, when and why, read-only', async () => {
    routes(['people.erase'], HELD);
    await openPrivacy();
    const section = await screen.findByTestId('person-legal-hold');
    const toggle = await within(section).findByRole('switch', { name: 'On legal hold' });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(toggle.hasAttribute('disabled')).toBe(true);
    const details = await within(section).findByTestId('legal-hold-details');
    expect(await within(details).findByText('Hina Admin')).toBeDefined();
    expect(details.textContent).toContain('Tribunal case 42');
  });

  it('putting it on needs a reason and sends If-Match from the hold read', async () => {
    const fake = routes(['audit.manage_holds'], FREE, {
      'PUT /api/v1/people/u-7/legal-hold': { body: { ...HELD, version: 4 } },
    });
    await openPrivacy();
    const section = await screen.findByTestId('person-legal-hold');
    fireEvent.click(await within(section).findByRole('switch', { name: 'On legal hold' }));
    const dialog = await screen.findByTestId('legal-hold-dialog');
    const ok = within(dialog).getByRole('button', { name: 'Put on hold' });
    expect(ok.hasAttribute('disabled')).toBe(true);
    fireEvent.change(within(dialog).getByLabelText('Reason'), {
      target: { value: 'Tribunal case 42' },
    });
    expect(ok.hasAttribute('disabled')).toBe(false);
    fireEvent.click(ok);
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/people/u-7/legal-hold')).toHaveLength(1);
    });
    const [put] = fake.find('PUT', '/api/v1/people/u-7/legal-hold');
    expect(put?.headers.get('If-Match')).toBe('"3"');
    expect(put?.body).toEqual({ reason: 'Tribunal case 42' });
  });

  it('lifting warns in plain words, needs a reason and confirms', async () => {
    const fake = routes(['audit.manage_holds'], HELD, {
      'POST /api/v1/people/u-7/legal-hold/lift': { body: { ...FREE, version: 4 } },
    });
    await openPrivacy();
    const section = await screen.findByTestId('person-legal-hold');
    fireEvent.click(await within(section).findByRole('switch', { name: 'On legal hold' }));
    const dialog = await screen.findByTestId('legal-hold-dialog');
    expect(within(dialog).getByTestId('legal-hold-lift-warning').textContent).toBe(
      'Once the hold is lifted, this person can be erased.',
    );
    const ok = within(dialog).getByRole('button', { name: 'Lift hold' });
    expect(ok.hasAttribute('disabled')).toBe(true);
    fireEvent.change(within(dialog).getByLabelText('Reason'), {
      target: { value: 'Case closed' },
    });
    fireEvent.click(ok);
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/people/u-7/legal-hold/lift')).toHaveLength(1);
    });
    const [post] = fake.find('POST', '/api/v1/people/u-7/legal-hold/lift');
    expect(post?.headers.get('If-Match')).toBe('"3"');
    expect(post?.body).toEqual({ reason: 'Case closed' });
  });
});

describe('the erasure request: files to keep', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/users');
  });

  it('lists the uploads by name and what they are attached to, with no download link', async () => {
    routes(['people.erase'], FREE);
    await openPrivacy();
    fireEvent.click(await screen.findByTestId('person-erasure-ask'));
    const files = await screen.findByTestId('erasure-keep-files');
    expect(await within(files).findByText('Keep contract.pdf')).toBeDefined();
    expect(files.textContent).toContain('Attached to: Record');
    expect(files.textContent).toContain('Not attached to anything');
    expect(files.textContent).not.toContain('work_item');
    expect(within(files).queryAllByRole('link')).toHaveLength(0);
  });

  it('a kept file needs its reason, sent with the request', async () => {
    const fake = routes(['people.erase'], FREE, {
      'POST /api/v1/people/u-7/erasure': { status: 201, body: {} },
    });
    await openPrivacy();
    fireEvent.click(await screen.findByTestId('person-erasure-ask'));
    const ask = await screen.findByTestId('erasure-request');
    await pick('erasure-request-reason', 'The person asked');
    await pick('erasure-request-successor', 'Hina Admin');
    fireEvent.change(within(ask).getByTestId('erasure-request-name'), {
      target: { value: 'Noor Hassan' },
    });
    const submit = within(ask).getByTestId('erasure-request-submit');
    expect(submit.hasAttribute('disabled')).toBe(false);
    fireEvent.click(await within(ask).findByTestId('erasure-keep-f-1'));
    expect(submit.hasAttribute('disabled')).toBe(true);
    // The reason field is labelled by the file's name (htmlFor/id).
    fireEvent.change(within(ask).getByLabelText('Why keep contract.pdf'), {
      target: { value: 'Signed contract, kept by law' },
    });
    expect(submit.hasAttribute('disabled')).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/people/u-7/erasure')).toHaveLength(1);
    });
    const [post] = fake.find('POST', '/api/v1/people/u-7/erasure');
    expect(post?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(post?.body).toMatchObject({
      reason_code: 'subject_request',
      successor_id: 'u-admin-2',
      keep_files: { 'f-1': 'Signed contract, kept by law' },
      confirm_name: 'Noor Hassan',
    });
  });
});
