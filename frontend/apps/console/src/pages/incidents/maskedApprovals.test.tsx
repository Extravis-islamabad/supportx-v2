import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// D-180 (0188), lane A's #594 note: the approver on the Approvals tab and the technician in the
// Details panel show the labelled stand-in to a vendor support session whose grant masks names,
// never an empty name; a session that doesn't mask sees the name (the control).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const TECH = '01900000-0000-7000-8000-0000000000a1';
const APPROVER = '01900000-0000-7000-8000-0000000000a2';
const APPROVAL = '01900000-0000-7000-8000-0000000000b1';

function session(namesMasked: boolean) {
  const base = fakeSession({ roles: ['technician'] });
  return {
    ...base,
    user: { ...base.user, user_type: 'vendor_support' as const },
    support: {
      grant_id: '01900000-0000-7000-8000-0000000000aa',
      access: 'view' as const,
      ends_at: '2099-01-01T10:00:00Z',
      contacts_masked: true,
      names_masked: namesMasked,
    },
  };
}

async function open(namesMasked: boolean, tech: string, approver: string) {
  // The API sends an empty name to a masked session (and no e-mail to any support session).
  const item = fakeIncident({
    technician_id: TECH,
    people: { [TECH]: { display_name: tech, email: '' } },
  });
  const path = `/api/v1/incidents/${item.id}`;
  const fake = consoleApi({
    me: session(namesMasked),
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
      [`GET ${path}`]: { body: item },
      [`GET ${path}/history`]: { body: { items: [], next_cursor: null, people: {} } },
      [`GET ${path}/approvals`]: {
        body: {
          items: [
            {
              id: APPROVAL,
              approver_id: APPROVER,
              state: 'pending',
              decided_at: null,
              comment: null,
              comments_required: false,
              can_decide: false,
              version: 1,
            },
          ],
          people: { [APPROVER]: { display_name: approver, email: '' } },
        },
      },
    },
  });
  restore = fake.restore;
  window.history.pushState({}, '', `/incidents/${item.id}`);
  render(<App />);
  const assignment = await screen.findByTestId('inc-panel-assignment');
  fireEvent.click(await screen.findByRole('tab', { name: 'Approvals' }));
  const row = await screen.findByTestId(`inc-approval-${APPROVAL}`);
  return { assignment, row };
}

describe('approvals and the Details panel with a masked support session', () => {
  it('the approver and the technician say "Person hidden", never an empty name', async () => {
    const { assignment, row } = await open(true, '', '');
    await waitFor(() => {
      expect(assignment.textContent).toContain('Person hidden');
    });
    expect(within(row).getByText('Person hidden')).toBeDefined();
  });

  it("a session that doesn't mask sees both names (control)", async () => {
    const { assignment, row } = await open(false, 'Tariq Tech', 'Amal Approver');
    await waitFor(() => {
      expect(assignment.textContent).toContain('Tariq Tech');
    });
    expect(within(row).getByText('Amal Approver')).toBeDefined();
    expect(assignment.textContent).not.toContain('Person hidden');
    expect(row.textContent).not.toContain('Person hidden');
  });
});
