import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import type { Erasure, ErasureMention, ErasureReport, UserDetail } from '@supportx/api-client';
import { fakePermissions } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession, fakeUser, problem } from '../../../test/api';
import { marked } from './erasureText';

/**
 * The app with motion off: a closing dialog keeps its last content until its leave animation
 * ends (rc-dialog), and jsdom never ends one; `destroyOnHidden` then removes it at once.
 */
function Shown() {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App />
    </ConfigProvider>
  );
}

// The erasure screens (ADR-052, D-171) over a mocked API only: no erasure runs anywhere.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const ME = '01900000-0000-7000-8000-000000000101';
const OTHER_ADMIN = 'u-admin-2';
const CHANNEL = 't:demo:queue:person_erasures';

const NOOR: UserDetail = fakeUser({
  id: 'u-7',
  display_name: 'Noor Hassan',
  first_name: 'Noor',
  last_name: 'Hassan',
  email: 'noor@demo.test',
  user_type: 'requester',
  version: 3,
});
const SAMIR: UserDetail = fakeUser({ id: 'u-8', display_name: 'Samir Khan' });
const ADMIN2: UserDetail = fakeUser({ id: OTHER_ADMIN, display_name: 'Hina Admin' });

const REPORT: ErasureReport = {
  complete: true,
  building: false,
  by_module: { work_items: { name: 2, email: 1 }, knowledge: { name: 1 } },
  ports_missing: [],
  attachment_content_searched: false,
  mail_bodies_searched: false,
  short_name_not_searched: false,
  reviewed_at: '2026-11-16T10:00:00Z',
  reviewed_by: OTHER_ADMIN,
};

function erasure(overrides: Partial<Erasure> = {}): Erasure {
  return {
    id: 'e-1',
    person_id: 'u-7',
    state: 'requested',
    step: 0,
    steps: 8,
    attempts: 0,
    reason_code: 'subject_request',
    reason_text: 'Asked by e-mail',
    successor_id: 'u-8',
    effective_successor_id: null,
    keep_files: {},
    requested_by: OTHER_ADMIN,
    requested_at: '2026-11-16T09:00:00Z',
    expires_at: '2026-11-23T09:00:00Z',
    approved_by: null,
    approved_at: null,
    rejected_by: null,
    rejected_at: null,
    started_at: null,
    finished_at: null,
    last_error_code: null,
    report_ready: true,
    report: REPORT,
    counts: {},
    holdings: { assets_held: 2 },
    version: 5,
    ...overrides,
  };
}

const MENTION: ErasureMention = {
  id: 'm-1',
  module_key: 'work_items',
  record_type: 'work_item',
  record_id: 'wi-1',
  field: 'description',
  match_kind: 'name',
  occurrences: 2,
  state: 'found',
  redacted_by: null,
  redacted_at: null,
  reaches_record_history: false,
  history_kept: 0,
};

function session() {
  return fakeSession(
    { display_name: 'Tariq Technician', roles: ['tenant_admin'] },
    {
      permissions: [
        ...fakePermissions('tenant_admin'),
        ...['people.erase', 'audit.view'].map((key) => ({
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
  shown: Erasure,
  extra: NonNullable<Parameters<typeof consoleApi>[0]>['routes'] = {},
) {
  const fake = consoleApi({
    me: session(),
    routes: {
      'GET /api/v1/erasures': { body: { items: [shown] } },
      'GET /api/v1/erasures/e-1': { body: shown, headers: { ETag: `"${String(shown.version)}"` } },
      'GET /api/v1/erasures/e-1/mentions': {
        body: { items: [MENTION], next_cursor: null, report: shown.report },
      },
      'GET /api/v1/erasures/e-1/mentions/m-1/passage': {
        body: { mention_id: 'm-1', text: 'Call Noor Hassan about the laptop.' },
      },
      'GET /api/v1/audit/entries': { body: { items: [], has_more: false, next_cursor: null } },
      'GET /api/v1/users/u-7': { body: NOOR },
      'GET /api/v1/users/u-8': { body: SAMIR },
      [`GET /api/v1/users/${OTHER_ADMIN}`]: { body: ADMIN2 },
      'GET /api/v1/realtime/lists/person_erasures': { body: { channels: [CHANNEL] } },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

async function openRecord() {
  window.history.pushState({}, '', '/admin/erasures/e-1');
  render(<Shown />);
  return screen.findByTestId('erasure-page');
}

describe('Admin › Erasures: the list', () => {
  it('shows the person, the state in words and the step as "n/8" read as a step', async () => {
    routes(erasure({ state: 'running', step: 3 }));
    window.history.pushState({}, '', '/admin/erasures');
    render(<Shown />);
    const table = await screen.findByTestId('erasures-table');
    expect(await within(table).findByText('Noor Hassan')).toBeDefined();
    expect(within(table).getByTestId('erasure-state-e-1').textContent).toBe('In progress');
    // Shown as "3/8", read out as "Step 3 of 8" (hidden text, not a label on a span).
    expect(within(table).getByText('3/8').getAttribute('aria-hidden')).toBe('true');
    expect(within(table).getByText('Step 3 of 8').className).toBe('sx-visually-hidden');
    expect(table.textContent).not.toContain('running');
  });

  it('an erased person shows as "Erased person", never by ID', async () => {
    routes(erasure({ state: 'done', step: 8 }));
    window.history.pushState({}, '', '/admin/erasures');
    render(<Shown />);
    const table = await screen.findByTestId('erasures-table');
    fireEvent.mouseDown(within(screen.getByTestId('erasures-view')).getByRole('combobox'));
    fireEvent.click(await screen.findByTitle('All'));
    expect(await within(table).findByText('Erased person')).toBeDefined();
    expect(table.textContent).not.toContain('u-7');
  });

  it('refetches live when an erasure changes', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const fake = routes(erasure());
    window.history.pushState({}, '', '/admin/erasures');
    render(<Shown />);
    await screen.findByTestId('erasures-table');
    await waitFor(() => {
      expect(realtime.channels()).toContain(CHANNEL);
    });
    const before = fake.find('GET', '/api/v1/erasures').length;
    act(() => {
      realtime.publish(CHANNEL, { type: 'person_erasures.changed', ids: ['e-1'] });
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/erasures').length).toBe(before + 1);
    });
  });
});

describe('Admin › Erasures: one erasure', () => {
  it('the requester never sees Approve; they may withdraw', async () => {
    routes(erasure({ requested_by: ME }));
    const page = await openRecord();
    expect(within(page).queryByTestId('erasure-approve')).toBeNull();
    expect(await within(page).findByTestId('erasure-other-admin')).toBeDefined();
    fireEvent.click(within(page).getByTestId('erasure-actions-more'));
    expect(await screen.findByTestId('erasure-withdraw')).toBeDefined();
  });

  it('Approve stays off, with the reason, until the report is complete and reviewed', async () => {
    routes(erasure({ report: { ...REPORT, reviewed_at: null, reviewed_by: null } }));
    const page = await openRecord();
    const approve = await within(page).findByTestId('erasure-approve');
    expect((approve as HTMLButtonElement).disabled).toBe(true);
    expect(within(page).getByTestId('erasure-approve-why').textContent).toBe(
      "Review the report of where they're named first.",
    );
  });

  it('approving shows the holdings first and needs the name typed exactly', async () => {
    const fake = routes(erasure(), {
      'POST /api/v1/erasures/e-1/approve': { body: erasure({ state: 'approved', version: 6 }) },
    });
    const page = await openRecord();
    fireEvent.click(await within(page).findByTestId('erasure-approve'));
    const dialog = await screen.findByTestId('erasure-approve-dialog');
    expect(within(dialog).getByTestId('erasure-holdings').textContent).toContain(
      'Assets they still hold',
    );
    const ok = within(dialog).getByTestId<HTMLButtonElement>('erasure-approve-ok');
    fireEvent.change(within(dialog).getByTestId('erasure-approve-name'), {
      target: { value: 'Noor Hasan' },
    });
    expect(ok.disabled).toBe(true);
    fireEvent.change(within(dialog).getByTestId('erasure-approve-name'), {
      target: { value: '  noor   HASSAN ' },
    });
    expect(ok.disabled).toBe(false);
    fireEvent.click(ok);
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/erasures/e-1/approve')).toHaveLength(1);
    });
    const [post] = fake.find('POST', '/api/v1/erasures/e-1/approve');
    expect(post?.headers.get('If-Match')).toBe('"5"');
    expect(post?.body).toEqual({ confirm_name: 'noor   HASSAN' });
  });

  it('a missing part of the product is named by its label, never its key', async () => {
    routes(erasure(), {
      'POST /api/v1/erasures/e-1/approve': {
        status: 409,
        body: problem(409, 'erasure_port_missing', { params: { missing_ports: 'cmdb,files' } }),
      },
    });
    const page = await openRecord();
    fireEvent.click(await within(page).findByTestId('erasure-approve'));
    const dialog = await screen.findByTestId('erasure-approve-dialog');
    fireEvent.change(within(dialog).getByTestId('erasure-approve-name'), {
      target: { value: 'Noor Hassan' },
    });
    fireEvent.click(within(dialog).getByTestId('erasure-approve-ok'));
    const said = await within(dialog).findByTestId('erasure-said');
    expect(said.textContent).toContain('Configuration items');
    expect(said.textContent).toContain('Files');
    expect(said.textContent).not.toContain('cmdb');
    expect(said.textContent).not.toContain('erasure_port_missing');
  });

  it('a passage is fetched only when asked, and gone when closed', async () => {
    const fake = routes(erasure());
    const page = await openRecord();
    fireEvent.click(within(page).getByRole('tab', { name: 'Mentions report' }));
    const button = await screen.findByTestId('erasure-passage-m-1');
    expect(fake.find('GET', '/api/v1/erasures/e-1/mentions/m-1/passage')).toHaveLength(0);
    fireEvent.click(button);
    const text = await screen.findByTestId('erasure-passage-text');
    expect(text.querySelector('mark')?.textContent).toBe('Noor Hassan');
    fireEvent.click(screen.getByTestId('erasure-passage-close'));
    await waitFor(() => {
      expect(screen.queryByTestId('erasure-passage-text')).toBeNull();
    });
    const stored = Array.from({ length: window.localStorage.length }, (_, i) =>
      window.localStorage.getItem(window.localStorage.key(i) ?? ''),
    );
    expect(stored.join(' ')).not.toContain('laptop');
    fireEvent.click(button);
    await screen.findByTestId('erasure-passage-text');
    expect(fake.find('GET', '/api/v1/erasures/e-1/mentions/m-1/passage')).toHaveLength(2);
  });

  it('a passage you cannot read says so', async () => {
    routes(erasure(), {
      'GET /api/v1/erasures/e-1/mentions/m-1/passage': {
        status: 404,
        body: problem(404, 'erasure_mention_not_found'),
      },
    });
    const page = await openRecord();
    fireEvent.click(within(page).getByRole('tab', { name: 'Mentions report' }));
    fireEvent.click(await screen.findByTestId('erasure-passage-m-1'));
    expect((await screen.findByTestId('erasure-passage-none')).textContent).toBe(
      "You can't read this record.",
    );
  });

  it('redacts the selected mentions after a confirmation naming the count', async () => {
    const fake = routes(erasure(), {
      'POST /api/v1/erasures/e-1/mentions/redact': {
        body: { erasure: erasure({ version: 6 }), redacted: [{ ...MENTION, state: 'redacted' }] },
      },
    });
    const page = await openRecord();
    fireEvent.click(within(page).getByRole('tab', { name: 'Mentions report' }));
    fireEvent.click(await screen.findByLabelText('Select this mention'));
    const bar = await screen.findByTestId('erasure-mentions-selection');
    expect(bar.textContent).toContain('1 selected, at most 200');
    fireEvent.click(within(bar).getByTestId('erasure-redact'));
    expect(await screen.findAllByText('Redact 1 selected mentions?')).not.toHaveLength(0);
    fireEvent.click(await screen.findByRole('button', { name: 'Redact' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/erasures/e-1/mentions/redact')).toHaveLength(1);
    });
    const [post] = fake.find('POST', '/api/v1/erasures/e-1/mentions/redact');
    expect(post?.body).toEqual({ mention_ids: ['m-1'] });
    expect(post?.headers.get('If-Match')).toBe('"5"');
  });

  it('the report table labels modules and kinds; a report still building says so', async () => {
    routes(
      erasure({
        report_ready: false,
        report: { ...REPORT, complete: false, building: true, ports_missing: ['cmdb'] },
      }),
    );
    const page = await openRecord();
    fireEvent.click(within(page).getByRole('tab', { name: 'Mentions report' }));
    expect(await screen.findByTestId('erasure-report-building')).toBeDefined();
    expect(screen.getByTestId('erasure-report-missing').textContent).toContain(
      'Configuration items',
    );
    const table = screen.getByTestId('erasure-report-table');
    expect(table.textContent).toContain('Tickets');
    expect(table.textContent).not.toContain('work_items');
    expect(within(table).getAllByRole('columnheader')[0]?.getAttribute('scope')).toBe('col');
  });
});

describe('marking a passage', () => {
  it('marks each term, case aside, and nothing else', () => {
    const parts = marked('noor@demo.test wrote to NOOR HASSAN', ['Noor Hassan', 'noor@demo.test']);
    render(<p data-testid="p">{parts}</p>);
    const marks = screen.getByTestId('p').querySelectorAll('mark');
    expect([...marks].map((m) => m.textContent)).toEqual(['noor@demo.test', 'NOOR HASSAN']);
  });
});
