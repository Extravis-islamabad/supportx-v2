import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { clickAction } from '../../test/actions';
import { consoleApi } from '../../test/api';
import { rememberTab } from './tabs';

// WP-046b S1: asking for approval with a rule (REQ-INC-083), and the reason a closed incident's
// edit asks for (REQ-INC-101).

const SESSION_USER = '01900000-0000-7000-8000-000000000101';
const OTHER = '01900000-0000-7000-8000-0000000003c1';
const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null, people: {} } },
  [`GET ${PATH}/approvals`]: { body: { items: [], people: {} } },
  'GET /api/v1/users': {
    body: {
      items: [
        { id: SESSION_USER, display_name: 'Tariq Technician', email: 'tech@demo.test' },
        { id: OTHER, display_name: 'Amal Approver', email: 'amal@demo.test' },
      ],
      next_cursor: null,
    },
  },
};

let restore: () => void = () => undefined;

describe('Incident approvals and edit controls', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'details');
  });
  afterEach(() => {
    restore();
    setDefaultClientFactory(inertClientFactory);
  });

  it('the Approvals tab says when none were asked for', async () => {
    const fake = consoleApi({ routes: { ...COMMON, [`GET ${PATH}`]: { body: ITEM } } });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Approvals' }));
    expect(await screen.findByText('No approvals asked for.')).toBeDefined();
  });

  it('"Ask for approval" opens the dialog with the people and the rule', async () => {
    const fake = consoleApi({ routes: { ...COMMON, [`GET ${PATH}`]: { body: ITEM } } });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('inc-properties');
    await clickAction('inc-op-ask-approval');
    const dialog = await screen.findByTestId('inc-approval-dialog');
    expect(within(dialog).getByText('Approvers')).toBeDefined();
    // The rule shows once more than one person is named (one person: they decide).
    expect(within(dialog).queryByTestId('inc-approval-rule')).toBeNull();
  });

  it("a closed incident's edit asks why and sends it", async () => {
    const closed = {
      ...ITEM,
      status: 'closed',
      status_category: 'closed',
      impact_details: 'Old count',
      operations: ITEM.operations.map((o) =>
        o.action === 'edit' ? { ...o, allowed: true, reason: null, reason_mode: 'required' } : o,
      ),
    };
    const fake = consoleApi({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: closed },
        [`PATCH ${PATH}`]: { body: { ...closed, impact_details: 'New count', version: 2 } },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-edit-impact_details'));
    const why = await screen.findByTestId('inc-why-impact_details');
    fireEvent.change(screen.getByTestId('inc-input-impact_details'), {
      target: { value: 'New count' },
    });
    fireEvent.change(why, { target: { value: 'The final count came after closing.' } });
    fireEvent.click(screen.getByTestId('inc-save-impact_details'));
    await waitFor(() => {
      expect(fake.find('PATCH', PATH)).toHaveLength(1);
    });
    expect(fake.find('PATCH', PATH)[0]?.body).toMatchObject({
      impact_details: 'New count',
      edit_reason: 'The final count came after closing.',
    });
  });

  it("another approver's decision reaches the open Approvals tab live", async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const fake = consoleApi({ routes: { ...COMMON, [`GET ${PATH}`]: { body: ITEM } } });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Approvals' }));
    await screen.findByText('No approvals asked for.');
    await waitFor(() => {
      expect(realtime.channels().some((name) => name.endsWith(`:wi:${ITEM.id}`))).toBe(true);
    });
    const before = fake.find('GET', `${PATH}/approvals`).length;
    act(() => {
      realtime.publish(`:wi:${ITEM.id}`, { type: 'work_items.approvals_changed', ids: ['a1'] });
    });
    await waitFor(() => {
      expect(fake.find('GET', `${PATH}/approvals`).length).toBeGreaterThan(before);
    });
  });
});
