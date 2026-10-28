import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, problem } from '../../test/api';

// WP-029-FIX: the WP-029 QA report's findings on the incident screens, named after their IDs.

function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ROUTES = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/organization/departments': { body: [] },
  'GET /api/v1/incidents/assignees': { body: [] },
  'GET /api/v1/custom-fields': { body: [] },
  'GET /api/v1/users/u-1': {
    body: { id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' },
  },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  'GET /api/v1/users': {
    body: {
      items: [{ id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' }],
      has_more: false,
      next_cursor: null,
    },
  },
};

const REFUSED = problem(422, 'rule_refused', {
  params: {
    rule: 'Printers need a site',
    message: 'Pick the site the printer is at.',
    message_ar: 'اختر موقع الطابعة.',
    message_ur: 'پرنٹر کی جگہ منتخب کریں۔',
  },
});

/** Every notification on screen (Ant Design toasts), by its text. */
function toasts(): string[] {
  return [...document.querySelectorAll('.ant-notification-notice')].map((n) => n.textContent);
}

async function fillAndSave(): Promise<void> {
  fireEvent.change(await screen.findByTestId('inc-subject'), {
    target: { value: 'Printer jammed' },
  });
  fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-requester')));
  fireEvent.click(await screen.findByText('rana@demo.test'));
  fireEvent.click(screen.getByTestId('inc-save'));
}

describe('WP-029 QA: a business rule refuses a save', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents/new');
  });
  afterEach(() => {
    restore();
  });

  it("BUG-01: the refusal shows the rule's own message, never the {{message}} placeholder", async () => {
    api({ routes: { ...ROUTES, 'POST /api/v1/incidents': { status: 422, body: REFUSED } } });
    render(<App />);
    await fillAndSave();
    const shown = await screen.findByTestId('form-problem');
    expect(shown.textContent).toContain('Pick the site the printer is at.');
    expect(document.body.textContent).not.toContain('{{');
  });

  it('BUG-02: the refusal shows once, at the form; no error toast, no "Copy reference"', async () => {
    api({ routes: { ...ROUTES, 'POST /api/v1/incidents': { status: 422, body: REFUSED } } });
    render(<App />);
    await fillAndSave();
    await screen.findByTestId('form-problem');
    // Give the app-wide reporter its turn (it waits for the screen to handle the error).
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(toasts()).toEqual([]);
    expect(screen.queryByText('Copy reference')).toBeNull();
    expect(screen.getAllByText('Pick the site the printer is at.')).toHaveLength(1);
    // The form keeps what was typed, so the user can correct it and save again.
    expect(screen.getByTestId<HTMLInputElement>('inc-subject').value).toBe('Printer jammed');
  });

  it('BUG-02: a real failure (500) is still an error toast with its reference', async () => {
    api({
      routes: {
        ...ROUTES,
        'POST /api/v1/incidents': { status: 500, body: problem(500, 'internal_error') },
      },
    });
    render(<App />);
    await fillAndSave();
    await waitFor(() => {
      expect(toasts()).toHaveLength(1);
    });
    expect(toasts()[0]).toContain('Copy reference');
    expect(screen.queryByTestId('form-problem')).toBeNull();
  });
});

describe('WP-029 QA: handing over a new incident', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents/new');
  });
  afterEach(() => {
    restore();
  });

  it('C1: the hand-over dialog says "this incident" in lower case mid-sentence', async () => {
    api({
      routes: {
        ...ROUTES,
        'POST /api/v1/incidents': {
          status: 409,
          body: problem(409, 'would_lose_access', { params: {} }),
        },
      },
    });
    render(<App />);
    await fillAndSave();
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('Hand over this incident?');
    expect(dialog.textContent).toContain('This incident moves to');
    expect(dialog.textContent).not.toMatch(/\S This incident/);
  });
});

describe('WP-029 QA: a move limited to certain people', () => {
  const ITEM = fakeIncident();
  const PATH = `/api/v1/incidents/${ITEM.id}`;
  const LIMITED = {
    ...ITEM,
    actions: ITEM.actions.map((a) =>
      a.action === 'resolve'
        ? {
            ...a,
            allowed: false,
            reason: 'not_for_you',
            allowed_for: {
              roles: [
                { key: 'tenant_admin', name: 'Tenant administrator', system: true },
                { key: 'night_shift', name: 'Night shift', system: false },
              ],
              groups: ['Network'],
              relatives: ['requester'],
            },
          }
        : a,
    ),
  };
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  });
  afterEach(() => {
    restore();
  });

  it('C2: "only certain people" names the roles, groups and people who may run it', async () => {
    api({
      routes: {
        ...ROUTES,
        [`GET ${PATH}`]: { body: LIMITED, headers: { ETag: `"${String(ITEM.version)}"` } },
        [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null, people: {} } },
        [`GET ${PATH}/automation`]: { body: [] },
      },
    });
    render(<App />);
    const reason = await screen.findByTestId('inc-action-resolve-reason');
    fireEvent.mouseEnter(reason.firstElementChild ?? reason);
    const tip = await screen.findByRole('tooltip');
    expect(tip.textContent).toBe(
      'Only these may do this on this record: Tenant administrator, Night shift, members of Network, the requester.',
    );
  });
});
