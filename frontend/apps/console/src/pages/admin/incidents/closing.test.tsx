import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { IncidentCatalogue } from '@supportx/api-client';
import {
  fakeCustomField,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, problem } from '../../../test/api';

// WP-020f: Admin › Incidents › Closing, and "a requester reply resumes it" on paused statuses
// (REQ-INC-051, 094..098). Test names cite the requirement.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const COST = fakeCustomField({ key: 'cost', labels: { en: 'Repair cost' } });

function routes(catalogue: IncidentCatalogue = fakeIncidentCatalogue()) {
  return {
    'GET /api/v1/incidents/settings': { body: catalogue },
    'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/custom-fields': { body: [COST] },
  };
}

function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}

function open(path: string) {
  window.history.pushState({}, '', path);
  render(<App />);
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  restore();
});

describe('Admin › Incidents › Closing', () => {
  it('REQ-INC-094: the closure rules save with If-Match, custom fields offered by name', async () => {
    const saved = fakeIncidentCatalogue();
    saved.version = 2;
    saved.closure.close_requires = ['closure_code', 'custom.cost'];
    const fake = api({
      me: ADMIN,
      routes: {
        ...routes(),
        'PATCH /api/v1/incidents/settings/closure': { body: saved },
      },
    });
    open('/admin/incidents/closing');
    const select = await screen.findByTestId('settings-close-requires');
    fireEvent.mouseDown(selectorOf(select));
    // The list is long: search for it, as a person would.
    const search = select.querySelector('input');
    if (search === null) throw new Error('no search box');
    fireEvent.change(search, { target: { value: 'Repair' } });
    const option = await waitFor(() => {
      const found = [...document.querySelectorAll('.ant-select-item-option-content')].find(
        (o) => o.textContent === 'Repair cost',
      );
      if (found === undefined) throw new Error('no option');
      return found;
    });
    fireEvent.click(option);
    fireEvent.click(screen.getByTestId('settings-closing-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/incidents/settings/closure')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/incidents/settings/closure');
    expect(sent?.headers.get('If-Match')).toBe('"1"');
    expect(sent?.body).toMatchObject({
      resolve_requires: ['resolution'],
      close_requires: ['closure_code', 'custom.cost'],
      reopen_window_days: 7,
    });
    // Auto-close was not touched: not sent (the server refuses it without a channel).
    expect(sent?.body).not.toHaveProperty('auto_close_days');
  });

  it('REQ-INC-096 AC3: auto-close is off and disabled while no channel can tell requesters', async () => {
    api({ me: ADMIN, routes: routes() });
    open('/admin/incidents/closing');
    const toggle = await screen.findByTestId('settings-auto-close');
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(toggle.hasAttribute('disabled')).toBe(true);
    expect(screen.getByTestId('settings-auto-close-needs').textContent).toContain(
      'Requires requester notifications',
    );
    const days = screen.getByTestId('settings-auto-close-days');
    const input = days instanceof HTMLInputElement ? days : days.querySelector('input');
    expect(input?.disabled).toBe(true);
  });

  it('BUG-02: a channel that cannot reach requesters says why, in words', async () => {
    const catalogue = fakeIncidentCatalogue();
    catalogue.closure.requester_channel_states = [
      { channel: 'email', reason: 'mail_not_configured' },
    ];
    api({ me: ADMIN, routes: routes(catalogue) });
    open('/admin/incidents/closing');
    const reasons = await screen.findByTestId('settings-requester-channels');
    expect(reasons.textContent).toContain('E-mail');
    expect(reasons.textContent).toContain('no outgoing mail server is set up');
    expect(reasons.textContent).not.toContain('mail_not_configured');
  });

  it('REQ-INC-096 AC3: with a channel, auto-close can be switched on with business days', async () => {
    const catalogue = fakeIncidentCatalogue();
    catalogue.closure.requester_channels = ['email'];
    const saved = fakeIncidentCatalogue();
    saved.version = 2;
    saved.closure = { ...catalogue.closure, auto_close_days: 5 };
    const fake = api({
      me: ADMIN,
      routes: {
        ...routes(catalogue),
        'PATCH /api/v1/incidents/settings/closure': { body: saved },
      },
    });
    open('/admin/incidents/closing');
    const toggle = await screen.findByTestId('settings-auto-close');
    expect(screen.queryByTestId('settings-auto-close-needs')).toBeNull();
    fireEvent.click(toggle);
    const days = screen.getByTestId('settings-auto-close-days');
    const input = days instanceof HTMLInputElement ? days : days.querySelector('input');
    if (input === null) throw new Error('no number input');
    fireEvent.change(input, { target: { value: '31' } });
    fireEvent.click(screen.getByTestId('settings-closing-save'));
    expect(await screen.findByText('Maximum is 30.')).toBeDefined();
    expect(fake.find('PATCH', '/api/v1/incidents/settings/closure')).toHaveLength(0);
    fireEvent.change(input, { target: { value: '5' } });
    fireEvent.click(screen.getByTestId('settings-closing-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/incidents/settings/closure')).toHaveLength(1);
    });
    expect(fake.find('PATCH', '/api/v1/incidents/settings/closure')[0]?.body).toMatchObject({
      auto_close_days: 5,
    });
  });

  it('REQ-INC-096 AC3: the server refusing auto-close shows the reason at the field', async () => {
    const catalogue = fakeIncidentCatalogue();
    catalogue.closure.requester_channels = ['email'];
    api({
      me: ADMIN,
      routes: {
        ...routes(catalogue),
        'PATCH /api/v1/incidents/settings/closure': {
          status: 422,
          body: problem(422, 'validation_failed', {
            errors: [
              {
                field: 'body.auto_close_days',
                code: 'auto_close_needs_notifications',
                message_key: 'errors.field.auto_close_needs_notifications',
                params: {},
              },
            ],
          }),
        },
      },
    });
    open('/admin/incidents/closing');
    fireEvent.click(await screen.findByTestId('settings-auto-close'));
    fireEvent.click(screen.getByTestId('settings-closing-save'));
    expect(
      await screen.findByText(
        'Auto-close needs requester notifications: no channel can tell requesters of a resolution yet.',
      ),
    ).toBeDefined();
  });

  it('REQ-INC-095: open-work settings per kind, with a note that the checks come later', async () => {
    api({ me: ADMIN, routes: routes() });
    open('/admin/incidents/closing');
    expect((await screen.findByTestId('settings-open-work-note')).textContent).toContain(
      'start working when tasks',
    );
    expect(screen.getByTestId('settings-open-work-approvals').textContent).toBe('Do not allow');
    expect(screen.getByTestId('settings-open-work-tasks').textContent).toBe(
      'Warn and ask to confirm',
    );
  });

  it('REQ-INC-051: "a requester reply resumes it" is offered on paused statuses only', async () => {
    const saved = fakeIncidentCatalogue();
    saved.version = 2;
    const fake = api({
      me: ADMIN,
      routes: {
        ...routes(),
        'PATCH /api/v1/incidents/settings/statuses/awaiting_requester': { body: saved },
      },
    });
    open('/admin/incidents/statuses');
    const toggle = await screen.findByTestId('status-resume-awaiting_requester');
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(screen.queryByTestId('status-resume-in_progress')).toBeNull();
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(
        fake.find('PATCH', '/api/v1/incidents/settings/statuses/awaiting_requester'),
      ).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/incidents/settings/statuses/awaiting_requester');
    expect(sent?.body).toEqual({ resume_on_requester_reply: false });
    expect(sent?.headers.get('If-Match')).toBe('"1"');
  });

  it('REQ-INC-094: the Closing screen is in Arabic, right to left', async () => {
    api({ me: fakeSession({ roles: ['tenant_admin'], locale: 'ar' }), routes: routes() });
    open('/admin/incidents/closing');
    expect((await screen.findByTestId('settings-auto-close-needs')).textContent).toContain(
      'يتطلب إشعارات مقدّمي الطلبات',
    );
    await waitFor(() => {
      expect(document.documentElement.dir).toBe('rtl');
    });
  });
});
