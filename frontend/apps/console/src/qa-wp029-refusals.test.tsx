import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { RuleOut, UserDetail } from '@supportx/api-client';
import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from './App';
import { consoleApi, fakeSession, fakeUser, problem } from './test/api';

// WP-029 QA BUG-02, app-wide: an expected refusal (a business rule, a validation) shows once, at
// the form, dialog or drawer that made the save, in the user's language; never as a red error
// toast with "Copy reference". Error toasts are kept for real failures.

type Routes = NonNullable<NonNullable<Parameters<typeof consoleApi>[0]>['routes']>;

let restore: () => void = () => undefined;
function api(routes: Routes) {
  const fake = consoleApi({ me: ADMIN, routes });
  restore = fake.restore;
  return fake;
}

afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ANSWERED = { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 };
const RULE_TEXT = 'Contractors are added by the service desk only.';
/** A business rule's refusal: a 422 problem with no field to point at. */
const REFUSED = problem(422, 'rule_refused', {
  params: { rule: 'Contractors', message: RULE_TEXT },
});

/** Notifications (Ant Design toasts and notices) that repeat the refusal. */
function noticesSaying(text: string): Element[] {
  return [...document.querySelectorAll('.ant-notification-notice')].filter((notice) =>
    notice.textContent.includes(text),
  );
}

/** Let the app-wide reporter have its turn (it waits for the screen to handle the error). */
async function reporterTurn(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 50));
}

function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}

const BILAL: UserDetail = fakeUser({
  id: 'u-9',
  display_name: 'Bilal Saleh',
  first_name: 'Bilal',
  last_name: 'Saleh',
  email: 'bilal@demo.test',
  user_type: 'requester',
  version: 4,
});
const PEOPLE: Routes = {
  'GET /api/v1/access-settings': { body: ANSWERED },
  'GET /api/v1/users': { body: { items: [BILAL], has_more: false, next_cursor: null } },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/organization/departments': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
};

async function addNoor(): Promise<HTMLElement> {
  window.history.pushState({}, '', '/admin/users');
  render(<App />);
  fireEvent.click(await screen.findByTestId('people-add'));
  fireEvent.change(await screen.findByTestId('person-first-name'), {
    target: { value: 'Noor' },
  });
  fireEvent.click(screen.getByTestId('person-save'));
  return screen.getByTestId('person-form');
}

describe('BUG-02: refusals show at the form, app-wide', () => {
  it('BUG-02: the people editor shows a refused save in the drawer, with no toast', async () => {
    api({ ...PEOPLE, 'POST /api/v1/users': { status: 422, body: REFUSED } });
    const form = await addNoor();
    const shown = await within(form).findByTestId('form-problem');
    expect(shown.textContent).toContain(RULE_TEXT);
    await reporterTurn();
    expect(document.querySelectorAll('.ant-notification-notice')).toHaveLength(0);
    expect(screen.queryByText('Copy reference')).toBeNull();
    expect(screen.getAllByText(RULE_TEXT)).toHaveLength(1);
    // What was typed stays, to be corrected and saved again.
    expect(screen.getByTestId<HTMLInputElement>('person-first-name').value).toBe('Noor');
  });

  it('BUG-02: the people editor clears the refusal when saving again', async () => {
    let calls = 0;
    api({
      ...PEOPLE,
      'POST /api/v1/users': () => {
        calls += 1;
        return calls === 1 ? { status: 422, body: REFUSED } : { body: BILAL };
      },
    });
    const form = await addNoor();
    await within(form).findByTestId('form-problem');
    fireEvent.click(screen.getByTestId('person-save'));
    await waitFor(() => {
      expect(screen.queryByTestId('form-problem')).toBeNull();
    });
  });

  it('BUG-02: a real failure (500) in the people editor is still an error toast', async () => {
    api({ ...PEOPLE, 'POST /api/v1/users': { status: 500, body: problem(500, 'internal_error') } });
    await addNoor();
    await waitFor(() => {
      expect(noticesSaying('Copy reference')).toHaveLength(1);
    });
    expect(screen.queryByTestId('form-problem')).toBeNull();
  });

  it('BUG-02: a business-rule editor shows a refused save in its drawer, with no toast', async () => {
    const rule: RuleOut = {
      id: 'r-1',
      record_type: 'incident',
      name: 'VIP first',
      description: null,
      events: ['create'],
      conditions: null,
      actions: [{ kind: 'set', field: 'priority', value: 'p1', mode: 'overwrite' }],
      stop_after: false,
      state: 'enabled',
      position: 1,
      site_id: null,
      owner_id: null,
      updated_at: '2026-10-27T08:00:00Z',
      version: 1,
    };
    api({
      'GET /api/v1/access-settings': { body: ANSWERED },
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/organization/departments': { body: [] },
      'GET /api/v1/automation/fields': {
        body: [
          {
            name: 'priority',
            kind: 'code',
            values: ['p1', 'p2', 'p3', 'p4'],
            settable: true,
            derived: false,
          },
        ],
      },
      'GET /api/v1/automation/rules': { body: [rule] },
      // Not a validation: a refusal with no problem list to show (no permission).
      'PATCH /api/v1/automation/rules/r-1': {
        status: 403,
        body: problem(403, 'permission_denied'),
      },
    });
    window.history.pushState({}, '', '/admin/automation/business-rules');
    render(<App />);
    fireEvent.click(await screen.findByText('VIP first'));
    fireEvent.change(await screen.findByTestId('rule-name'), {
      target: { value: 'VIP first!' },
    });
    fireEvent.click(screen.getByTestId('rule-save'));
    const editor = screen.getByTestId('rule-editor');
    const shown = await within(editor).findByTestId('form-problem');
    expect(shown.textContent).toContain('You do not have permission to do this.');
    await reporterTurn();
    expect(noticesSaying('You do not have permission to do this.')).toHaveLength(0);
    expect(screen.queryByText('Copy reference')).toBeNull();
  });

  it('BUG-02: a refused status move shows in its reason dialog, with no toast', async () => {
    const item = fakeIncident();
    const path = `/api/v1/incidents/${item.id}`;
    api({
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
      [`GET ${path}`]: { body: item, headers: { ETag: '"1"' } },
      [`POST ${path}/actions/cancel`]: { status: 422, body: REFUSED },
    });
    window.history.pushState({}, '', `/incidents/${item.id}`);
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-cancel'));
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-reason-code')));
    fireEvent.click(await screen.findByTitle('Duplicate'));
    fireEvent.click(screen.getByTestId('inc-reason-confirm'));
    const shown = await screen.findByTestId('form-problem');
    // In the dialog, which stays open so the user can change their mind or the reason.
    expect(shown.closest('.ant-modal')).not.toBeNull();
    expect(shown.textContent).toContain(RULE_TEXT);
    expect(screen.getByTestId('inc-reason-confirm')).toBeDefined();
    await reporterTurn();
    expect(noticesSaying(RULE_TEXT)).toHaveLength(0);
    expect(screen.queryByText('Copy reference')).toBeNull();
  });
});
