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
    // One save bar (template E): none until something changes.
    const scope = await screen.findByRole('combobox', { name: 'Requesters may raise for' });
    expect(screen.queryByTestId('sr-settings-save-bar')).toBeNull();
    fireEvent.mouseDown(scope);
    fireEvent.click(await screen.findByTitle('Any requester'));
    expect((await screen.findByTestId('sr-settings-save-bar')).textContent).toContain(
      '1 unsaved change',
    );
    fireEvent.click(screen.getByTestId('settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/service-requests/settings')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/service-requests/settings');
    expect(sent?.body).toEqual({ on_behalf_scope: 'all_requesters' });
    expect(sent?.headers.get('If-Match')).toBe('"4"');
  });

  it('D-154c: the first-task switch is on by default and saves through the bar', async () => {
    window.history.pushState({}, '', '/admin/requests');
    const fake = consoleApi({
      me: fakeSession({ roles: ['tenant_admin'] }),
      routes: {
        'GET /api/v1/service-requests/settings': { body: saved },
        'PATCH /api/v1/service-requests/settings': {
          body: { ...saved, first_task_starts_work: false, version: 5 },
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    const starts = await screen.findByTestId('sr-first-task-starts');
    expect(starts.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(starts);
    fireEvent.click(await screen.findByTestId('settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/service-requests/settings')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/service-requests/settings');
    expect(sent?.body).toEqual({ first_task_starts_work: false });
  });
});
