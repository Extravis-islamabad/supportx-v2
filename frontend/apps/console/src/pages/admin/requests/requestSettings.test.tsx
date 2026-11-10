import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-030 s1 (REQ-SR-011): the admin sets whom a requester may raise a request for.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const saved = { ...fakeIncidentCatalogue(), prefix: 'SR', version: 4 };

describe('console: service request settings', () => {
  it('saves the on-behalf scope with If-Match on the version shown', async () => {
    window.history.pushState({}, '', '/admin/requests');
    const fake = consoleApi({
      me: fakeSession({ roles: ['tenant_admin'] }),
      routes: {
        'GET /api/v1/service-requests/settings': { body: saved },
        'PATCH /api/v1/service-requests/settings': {
          body: { ...saved, on_behalf_scope: 'all_requesters', version: 5 },
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    const save = await screen.findByTestId('sr-settings-save');
    expect(save.closest('button')?.disabled).toBe(true); // nothing changed yet
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Requesters may raise for' }));
    fireEvent.click(await screen.findByTitle('Any requester'));
    fireEvent.click(save);
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/service-requests/settings')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/service-requests/settings');
    expect(sent?.body).toEqual({ on_behalf_scope: 'all_requesters' });
    expect(sent?.headers.get('If-Match')).toBe('"4"');
  });
});
