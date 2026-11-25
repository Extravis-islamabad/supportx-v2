import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { HeldElsewhere } from '@supportx/api-client';

import { App } from '../App';
import { consoleApi, fakeSession } from '../test/api';

// D-188 (WP-057 S5c-1b): the profile says which access only another sign-in applies, by name,
// never a code or an ID, and says nothing when there is none.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ME = fakeSession({ display_name: 'Tariq Tech', roles: ['technician'] });
const HELD: HeldElsewhere[] = [
  {
    kind: 'role',
    id: '11111111-1111-4111-8111-111111111111',
    name: 'Change reviewers',
    role_key: 'change_reviewers',
    is_system: false,
    provider_name: 'Acme sign-in',
  },
  {
    kind: 'group',
    id: '22222222-2222-4222-8222-222222222222',
    name: 'Network desk',
    role_key: null,
    is_system: false,
    provider_name: 'Acme sign-in',
  },
];

describe('My profile › access from your sign-in group', () => {
  it('names what only that sign-in applies, and the sign-in', async () => {
    window.history.pushState({}, '', '/profile');
    restore = consoleApi({
      me: ME,
      routes: { 'GET /api/v1/identity/my-access/elsewhere': () => ({ body: HELD }) },
    }).restore;
    render(<App />);
    const note = await screen.findByTestId('profile-sign-in-group-access');
    expect(note.textContent).toContain('only applies when you sign in with Acme sign-in');
    expect(within(note).getByText('Change reviewers and Network desk')).toBeTruthy();
    expect(note.textContent).not.toContain('11111111');
    expect(note.textContent).not.toContain('change_reviewers');
  });

  it('shows nothing when no access is held elsewhere', async () => {
    window.history.pushState({}, '', '/profile');
    restore = consoleApi({ me: ME }).restore;
    render(<App />);
    await screen.findByTestId('profile-header');
    expect(screen.queryByTestId('profile-sign-in-group-access')).toBeNull();
  });
});
