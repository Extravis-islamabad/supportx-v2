import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// WP-046b S4 (REQ-INC-126): the printable incident asks the server for public entries only when
// "public notes only" is chosen, so a private note never reaches the page (AC1, lane B).

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ITEM = fakeIncident({ subject: 'Mail relay down' });
const PATH = `/api/v1/incidents/${ITEM.id}`;

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function entry(id: string, visibility: 'public' | 'private', text: string) {
  return {
    id,
    kind: 'note',
    visibility,
    reply_mode: null,
    body: `<p>${text}</p>`,
    recipients: null,
    delivery_state: null,
    created_at: '2026-11-17T09:00:00Z',
    created_by: ADMIN.user.id,
  };
}

describe('Print an incident', () => {
  it('public notes only: the server is asked for public entries, and only those show', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: {
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
        [`GET ${PATH}`]: { body: ITEM },
        [`GET ${PATH}/conversation`]: ({ url }) => ({
          body: {
            items:
              url.searchParams.get('visibility') === 'public'
                ? [entry('e-1', 'public', 'Restarted the mail relay')]
                : [
                    entry('e-1', 'public', 'Restarted the mail relay'),
                    entry('e-2', 'private', 'Vendor PIN 4411'),
                  ],
            truncated: false,
            people: {},
          },
        }),
      },
    });
    restore = fake.restore;
    window.history.pushState({}, '', `/incidents/${ITEM.id}/print?s=conversation&notes=public`);
    render(<App />);
    expect(await screen.findByText('Restarted the mail relay')).toBeTruthy();
    await waitFor(() => {
      const asked = fake.find('GET', `${PATH}/conversation`);
      expect(asked.at(-1)?.url.searchParams.get('visibility')).toBe('public');
    });
    expect(screen.queryByText('Vendor PIN 4411')).toBeNull();
    expect(screen.queryByTestId('inc-print-entry-private')).toBeNull();
    // Only the chosen sections.
    expect(screen.queryByTestId('inc-print-history')).toBeNull();
  });
});
