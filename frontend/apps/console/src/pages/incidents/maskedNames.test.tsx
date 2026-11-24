import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  fakeConversationEntry,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// D-180 (0188), lane A's rule 8 OK: the incident parts that read a person's name directly
// (followers, the conversation's authors) show the labelled stand-in to a vendor support session
// whose grant masks names, never an empty name; a session that doesn't mask sees the name.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ITEM = fakeIncident({ conversation_count: 1 });
const PATH = `/api/v1/incidents/${ITEM.id}`;
const TECH = '01900000-0000-7000-8000-0000000000a1';

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

function routes(name: string) {
  // The API sends an empty name to a masked session (and no e-mail to any support session).
  const people = { [TECH]: { display_name: name, email: '' } };
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    'GET /api/v1/incidents/reply-templates': { body: [] },
    [`GET ${PATH}`]: { body: ITEM },
    [`GET ${PATH}/followers`]: {
      body: {
        items: [
          {
            user_id: TECH,
            reason: 'handed_over',
            grants_access: true,
            since: '2026-10-24T09:00:00Z',
            removable: false,
          },
        ],
        may_manage: false,
        people,
      },
    },
    [`GET ${PATH}/conversation`]: {
      body: {
        items: [fakeConversationEntry({ created_by: TECH })],
        truncated: false,
        people,
      },
    },
  };
}

async function open(namesMasked: boolean, name: string) {
  const fake = consoleApi({ me: session(namesMasked), routes: routes(name) });
  restore = fake.restore;
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  render(<App />);
  const card = await screen.findByTestId('inc-followers');
  const follower = await within(card).findByTestId('inc-follower');
  fireEvent.click(await screen.findByRole('tab', { name: /^Conversation/ }));
  const timeline = await screen.findByTestId('conv-timeline');
  return { follower, timeline };
}

describe('incident parts with a masked support session', () => {
  it('followers and the conversation say "Person hidden", never an empty name', async () => {
    const { follower, timeline } = await open(true, '');
    await waitFor(() => {
      expect(follower.textContent).toContain('Person hidden');
    });
    await waitFor(() => {
      expect(timeline.textContent).toContain('Person hidden');
    });
  });

  it("a session that doesn't mask sees the name (control)", async () => {
    const { follower, timeline } = await open(false, 'Tariq Tech');
    await waitFor(() => {
      expect(follower.textContent).toContain('Tariq Tech');
    });
    await waitFor(() => {
      expect(timeline.textContent).toContain('Tariq Tech');
    });
    expect(follower.textContent).not.toContain('Person hidden');
  });
});
