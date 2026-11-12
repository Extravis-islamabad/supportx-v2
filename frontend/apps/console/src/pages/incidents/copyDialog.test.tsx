import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  type FakeRoute,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { clickAction } from '../../test/actions';
import { consoleApi, fakeSession } from '../../test/api';
import { rememberTab } from './tabs';

// WP-046a S5c (REQ-INC-033): copy an incident one or more times from its page.

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;

function routes(copies: FakeRoute) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    [`GET ${PATH}`]: { body: ITEM, headers: { ETag: `"${String(ITEM.version)}"` } },
    [`GET ${PATH}/conversation`]: { body: { items: [], people: {} } },
    [`POST ${PATH}/copies`]: copies,
  };
}

let restore: () => void = () => undefined;
beforeEach(() => {
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  rememberTab(ADMIN.user.id, 'details');
});
afterEach(() => {
  restore();
});

describe('Copy an incident', () => {
  it('AC1: sends the count and the chosen parts with a key, and names the copies made', async () => {
    const copies = [
      { ...ITEM, id: 'c-1', display_id: 'INC-11' },
      { ...ITEM, id: 'c-2', display_id: 'INC-12' },
    ];
    const fake = consoleApi({
      me: ADMIN,
      routes: routes({ status: 201, body: { items: copies } }),
    });
    restore = fake.restore;
    render(<App />);
    await clickAction('inc-op-copy');
    fireEvent.change(await screen.findByTestId('inc-copy-count'), { target: { value: '2' } });
    fireEvent.click(screen.getByTestId('inc-copy-tasks'));
    fireEvent.click(screen.getByTestId('inc-copy-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/copies`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `${PATH}/copies`);
    expect(sent?.body).toEqual({ count: 2, parts: ['tasks'] });
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(await screen.findByText('Made INC-11 and INC-12.')).toBeDefined();
  });

  it('AC3: a refusal over the limit says the limit at the count', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: routes({
        status: 422,
        body: {
          type: 'about:blank',
          title: 'Validation failed',
          status: 422,
          code: 'validation_failed',
          message_key: 'errors.validation_failed',
          errors: [
            {
              field: 'body.count',
              code: 'too_many_copies',
              message_key: 'errors.field.too_many_copies',
              params: { max: 20 },
            },
          ],
        },
      }),
    });
    restore = fake.restore;
    render(<App />);
    await clickAction('inc-op-copy');
    fireEvent.change(await screen.findByTestId('inc-copy-count'), { target: { value: '25' } });
    fireEvent.click(screen.getByTestId('inc-copy-confirm'));
    expect(await screen.findByText('Make 1 to 20 copies at a time.')).toBeDefined();
  });
});
