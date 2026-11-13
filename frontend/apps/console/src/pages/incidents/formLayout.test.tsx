import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue, fakeIncidentTemplate } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// WP-046a S5b: the create form follows the template's layout (REQ-INC-036 AC1) and applies its
// form rules live, the same way the server does on save (REQ-INC-037).

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

function routes(template: ReturnType<typeof fakeIncidentTemplate>) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/templates': { body: [template] },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  };
}

let restore: () => void = () => undefined;
beforeEach(() => {
  window.history.pushState({}, '', '/incidents/new');
});
afterEach(() => {
  restore();
  window.sessionStorage.clear();
});

describe('New incident: the designer layout and form rules', () => {
  it('REQ-INC-036 AC1: a field moved into a section shows there on the create form', async () => {
    const template = {
      ...fakeIncidentTemplate(),
      layout: {
        technician: {
          label_position: 'start' as const,
          sections: [
            {
              id: 'first',
              names: { en: 'First things' },
              columns: 1,
              collapsible: false,
              collapsed: false,
              fields: ['requester_id', 'subject'],
            },
            {
              id: 'rest',
              names: {} as Record<string, string>,
              columns: 2,
              collapsible: false,
              collapsed: false,
              fields: [],
            },
          ],
        },
        requester: null,
      },
    };
    restore = consoleApi({ me: ADMIN, routes: routes(template) }).restore;
    render(<App />);
    const first = await screen.findByTestId('inc-layout-first');
    expect(within(first).getByText('First things')).toBeDefined();
    expect(within(first).getByTestId('inc-subject')).toBeDefined();
    // The fields the layout does not place go to the last section, never lost.
    const rest = screen.getByTestId('inc-layout-rest');
    expect(within(rest).getByTestId('inc-channel')).toBeDefined();
    expect(within(rest).getByText('Section')).toBeDefined();
    // The classic sections are not drawn as well.
    expect(screen.queryByTestId('inc-section-request')).toBeNull();
  });

  it('a required field in a section that starts closed opens it on Save (lane C)', async () => {
    const base = fakeIncidentTemplate();
    const template = {
      ...base,
      fields: {
        ...base.fields,
        description: {
          shown: true,
          required: true,
          requester_can_see: true,
          requester_can_fill: true,
        },
      },
      layout: {
        technician: {
          label_position: 'top' as const,
          sections: [
            {
              id: 'first',
              names: { en: 'First' },
              columns: 1,
              collapsible: false,
              collapsed: false,
              fields: ['requester_id', 'subject'],
            },
            {
              id: 'more',
              names: { en: 'More' },
              columns: 1,
              collapsible: true,
              collapsed: true,
              fields: ['description'],
            },
          ],
        },
        requester: null,
      },
    };
    restore = consoleApi({ me: ADMIN, routes: routes(template) }).restore;
    render(<App />);
    const more = await screen.findByTestId('inc-layout-more');
    const panel = () => more.querySelector('.ant-collapse-item');
    expect(panel()?.className).not.toContain('ant-collapse-item-active');
    fireEvent.change(screen.getByTestId('inc-subject'), { target: { value: 'Printer jammed' } });
    fireEvent.click(screen.getByTestId('inc-save'));
    await waitFor(() => {
      expect(panel()?.className).toContain('ant-collapse-item-active');
    });
  });

  it('REQ-INC-037: rules hide and lock fields as soon as their condition holds', async () => {
    const template = {
      ...fakeIncidentTemplate(),
      form_rules: [
        {
          id: 'typed',
          when: { field: 'subject', op: 'is_not_null' },
          then: [
            { do: 'hide' as const, field: 'tags', value: null, keep_value: null },
            { do: 'lock' as const, field: 'channel', value: null, keep_value: null },
          ],
        },
      ],
    };
    restore = consoleApi({ me: ADMIN, routes: routes(template) }).restore;
    render(<App />);
    expect(await screen.findByTestId('inc-tags')).toBeDefined();
    const phone = within(screen.getByTestId('inc-channel')).getAllByRole('radio')[0];
    expect(phone?.hasAttribute('disabled')).toBe(false);
    fireEvent.change(screen.getByTestId('inc-subject'), { target: { value: 'Printer jammed' } });
    await waitFor(() => {
      expect(screen.queryByTestId('inc-tags')).toBeNull();
    });
    const locked = within(screen.getByTestId('inc-channel')).getAllByRole('radio')[0];
    expect(locked?.hasAttribute('disabled')).toBe(true);
  });
});
