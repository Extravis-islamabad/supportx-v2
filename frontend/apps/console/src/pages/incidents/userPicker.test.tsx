import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession, fakeUser } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// QA10-P4-16 (rule 5d): a chosen person not on the picker's loaded page (here the signed-in
// requester of a new release) is named, never shown as their raw id.

const ME = fakeSession();
const ID = ME.user.id;

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

describe('UserPicker', () => {
  it('names a chosen person missing from the loaded page, never their id', async () => {
    window.history.pushState({}, '', '/releases/new');
    const fake = consoleApi({
      me: ME,
      routes: {
        'GET /api/v1/users': { body: { items: [], has_more: false, next_cursor: null } },
        [`GET /api/v1/users/${ID}`]: {
          body: fakeUser({ id: ID, display_name: 'Nadia Iqbal' }),
        },
        'GET /api/v1/releases/templates': { body: [] },
      },
    });
    restore = fake.restore;
    render(<App />);
    const picker = await screen.findByTestId('release-requester');
    await waitFor(() => {
      expect(picker.textContent).toContain('Nadia Iqbal');
    });
    expect(document.body.textContent).not.toContain(ID);
  });
});
