import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  type FakeRoute,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// WP-046a S5c (REQ-INC-018): quick create from the list. The same create as the full form, so
// the template's starting values go with it and its rules still refuse what they need.

function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ITEM = fakeIncident();
const TEMPLATE = fakeIncidentTemplate({ id: 't-1', defaults: { category_id: 'c-net' } });

function routes(post: FakeRoute) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/templates': { body: [TEMPLATE] },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    'GET /api/v1/incidents': {
      body: {
        items: [{ ...ITEM, deleted_at: null }],
        has_more: false,
        next_cursor: null,
        estimated_total: 1,
        people: ITEM.people,
      },
    },
    'GET /api/v1/incidents/views': { body: [{ view: 'open', count: 1, capped: false }] },
    'GET /api/v1/users': {
      body: {
        items: [{ id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' }],
        has_more: false,
        next_cursor: null,
      },
    },
    'POST /api/v1/incidents': post,
  };
}

let restore: () => void = () => undefined;
beforeEach(() => {
  window.history.pushState({}, '', '/incidents');
});
afterEach(() => {
  restore();
});

async function fillIn() {
  fireEvent.click(await screen.findByTestId('inc-quick-open'));
  fireEvent.change(await screen.findByTestId('inc-quick-subject'), {
    target: { value: 'Printer jammed' },
  });
  fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-quick-requester')));
  fireEvent.click(await screen.findByText('rana@demo.test'));
  fireEvent.click(screen.getByTestId('inc-quick-create'));
}

describe('Quick create', () => {
  it("AC1: sends the template's starting values and the list loads the new row", async () => {
    const fake = consoleApi({ me: ADMIN, routes: routes({ status: 201, body: ITEM }) });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('inc-quick-open');
    const listed = fake.find('GET', '/api/v1/incidents').length;
    await fillIn();
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/incidents')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/incidents');
    expect(sent?.body).toMatchObject({
      subject: 'Printer jammed',
      requester_id: 'u-1',
      template_id: 't-1',
      category_id: 'c-net',
    });
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(await screen.findByText(`${ITEM.display_id} created.`)).toBeDefined();
    // The list is fetched again with the new row (live updates do the same from the event).
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/incidents').length).toBeGreaterThan(listed);
    });
  });

  it('AC2: a field a rule requires is named, with the way to the full form', async () => {
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
              field: 'body.site_id',
              code: 'required',
              message_key: 'errors.field.required',
              params: {},
            },
          ],
        },
      }),
    });
    restore = fake.restore;
    render(<App />);
    await fillIn();
    expect((await screen.findByTestId('inc-quick-needs')).textContent).toContain('Site');
    fireEvent.click(screen.getByTestId('inc-quick-full'));
    await waitFor(() => {
      expect(window.location.pathname).toBe('/incidents/new');
    });
    expect(window.location.search).toContain('template=t-1');
    expect(window.location.search).toContain('requester=u-1');
  });
});
