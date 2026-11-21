import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Incident } from '@supportx/api-client';
import {
  fakeCustomField,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-046b S5 (REQ-INC-148 AC1): a requester's waiting ask to cancel, on the record, and its
// decision by whoever may decide.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ITEM: Incident = {
  ...fakeIncident(),
  actions: [
    ...fakeIncident().actions.filter((a) => a.action !== 'cancel'),
    {
      action: 'cancel',
      allowed: true,
      reason: null,
      missing: [],
      reason_mode: 'required',
      reason_list: 'cancel',
    },
  ],
};
const PATH = `/api/v1/incidents/${ITEM.id}`;

function routes(mayDecide: boolean, extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/organization/departments': { body: [] },
    'GET /api/v1/custom-fields': { body: [fakeCustomField()] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    [`GET ${PATH}/conversation`]: { body: { items: [], people: {} } },
    [`GET ${PATH}/automation`]: { body: [] },
    [`GET ${PATH}`]: { body: ITEM, headers: { ETag: `"${String(ITEM.version)}"` } },
    [`GET ${PATH}/cancellation-request`]: {
      body: {
        id: '01900000-0000-7000-8000-00000000ca11',
        reason: 'It works again.',
        requested_by: '01900000-0000-7000-8000-000000000201',
        asked_at: '2026-11-21T08:00:00Z',
        may_decide: mayDecide,
        deciders: mayDecide ? 'assignee' : 'none',
      },
    },
    [`POST ${PATH}/cancellation-request/decide`]: { status: 204 },
    ...extra,
  } as Parameters<typeof consoleApi>[0] extends infer A
    ? A extends { routes?: infer R }
      ? R
      : never
    : never;
}

describe('A requester asked to cancel (WP-046b S5)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  });
  afterEach(() => {
    restore();
  });

  it('shows the ask; approving needs the cancel’s own reason code, and sends it', async () => {
    const fake = api({ routes: routes(true) });
    render(<App />);
    const strip = await screen.findByTestId('inc-cancellation-ask');
    expect(strip.textContent).toContain('It works again.');
    fireEvent.click(within(strip).getByTestId('inc-cancellation-approve'));
    const ok = await screen.findByTestId('inc-cancellation-ok');
    expect((ok as HTMLButtonElement).disabled).toBe(true); // the cancel needs a code here
    fireEvent.mouseDown(within(screen.getByTestId('inc-cancellation-code')).getByRole('combobox'));
    fireEvent.click(await screen.findByTitle(/duplicate/i));
    await waitFor(() => {
      expect(screen.getByTestId<HTMLButtonElement>('inc-cancellation-ok').disabled).toBe(false);
    });
    fireEvent.click(screen.getByTestId('inc-cancellation-ok'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/cancellation-request/decide`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${PATH}/cancellation-request/decide`)[0]?.body).toEqual({
      approve: true,
      reason_code: 'duplicate',
    });
  });

  it('declining needs a note for the requester', async () => {
    const fake = api({ routes: routes(true) });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-cancellation-decline'));
    expect((await screen.findByTestId<HTMLButtonElement>('inc-cancellation-ok')).disabled).toBe(
      true,
    );
    fireEvent.change(screen.getByTestId('inc-cancellation-note'), {
      target: { value: 'We still see the fault.' },
    });
    fireEvent.click(screen.getByTestId('inc-cancellation-ok'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/cancellation-request/decide`)[0]?.body).toEqual({
        approve: false,
        note: 'We still see the fault.',
      });
    });
  });

  it('someone who does not decide sees the ask, without the buttons', async () => {
    api({ routes: routes(false) });
    render(<App />);
    const strip = await screen.findByTestId('inc-cancellation-ask');
    expect(strip.textContent).toContain('It works again.');
    expect(within(strip).queryByTestId('inc-cancellation-approve')).toBeNull();
    expect(within(strip).getByTestId('inc-cancellation-deciders').textContent).toBe(
      'Nobody can decide this yet: assign it, or give someone the right',
    );
  });
});
