import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-046b S5 (REQ-INC-148): the tenant's requester cancel and edit rules, on General.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ROUTES = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/incidents/reply-templates': { body: [] },
  'GET /api/v1/incidents/reply-templates/manage': { body: [] },
  'PATCH /api/v1/incidents/settings': (call: { body: unknown }) => ({
    body: { ...fakeIncidentCatalogue(), ...(call.body as object), version: 2 },
  }),
};

// The test setup's matchMedia matches nothing, i.e. a phone: the cancel choice is a Segmented
// from 576 px and a Select below (qa-wp020c BUG-03). These tests set the width they mean.
let restoreWidth: () => void = () => undefined;
function screenWidth(wide: boolean): void {
  const saved = Object.getOwnPropertyDescriptor(window, 'matchMedia');
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: wide && query.includes('min-width'),
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
  restoreWidth = () => {
    if (saved !== undefined) Object.defineProperty(window, 'matchMedia', saved);
  };
}

beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, '', '/admin/incidents/general');
});
afterEach(() => {
  restoreWidth();
  restore();
});

describe('Requesters cancel and edit (WP-046b S5)', () => {
  it('off and none by default; both settings go in the one save, only when changed', async () => {
    screenWidth(true);
    const fake = api({ me: fakeSession({ roles: ['tenant_admin'] }), routes: ROUTES });
    render(<App />);
    const card = await screen.findByTestId('settings-requester-rules');
    const mode = within(card).getByTestId('settings-requester-cancel');
    expect(mode.querySelector('.ant-segmented-item-selected')?.textContent).toBe(
      'Requesters cannot cancel',
    );
    fireEvent.click(within(mode).getByText('Requesters ask; the team decides'));
    const fields = within(card).getByTestId('settings-requester-edit');
    const selector = fields.querySelector('.ant-select-selector');
    if (selector === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(selector);
    fireEvent.click(await screen.findByTitle('Subject'));
    fireEvent.click(screen.getByTestId('settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/incidents/settings')).toHaveLength(1);
    });
    expect(fake.find('PATCH', '/api/v1/incidents/settings')[0]?.body).toEqual({
      requester_cancel: 'ask',
      requester_edit_fields: ['subject'],
    });
  });

  it('on a phone the cancel choice is a Select: the same values, labels and order', async () => {
    screenWidth(false);
    const fake = api({ me: fakeSession({ roles: ['tenant_admin'] }), routes: ROUTES });
    render(<App />);
    const card = await screen.findByTestId('settings-requester-rules');
    const mode = within(card).getByTestId('settings-requester-cancel');
    expect(mode.classList.contains('ant-select')).toBe(true);
    expect(card.querySelector('.ant-segmented')).toBeNull();
    const selector = mode.querySelector('.ant-select-selector');
    if (selector === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(selector);
    // The dropdown's own items (antd's hidden accessibility list holds only a few `option`s).
    await waitFor(() => {
      expect(document.querySelectorAll('.ant-select-item-option')).toHaveLength(3);
    });
    const options = [...document.querySelectorAll('.ant-select-item-option')];
    expect(options.map((o) => o.getAttribute('title'))).toEqual([
      'Requesters cannot cancel',
      'Requesters cancel directly',
      'Requesters ask; the team decides',
    ]);
    const ask = options[2];
    if (ask === undefined) throw new Error('no third option');
    fireEvent.click(ask);
    fireEvent.click(screen.getByTestId('settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/incidents/settings')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/incidents/settings');
    expect((sent?.body as { requester_cancel?: string }).requester_cancel).toBe('ask');
  });
});
