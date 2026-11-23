import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { IncidentCatalogue } from '@supportx/api-client';
import { fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-058b S4: Admin › Releases — the incident settings screens, shared, writing the release
// settings (REQ-REL-048, 050, 052). Test names cite the requirement.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ roles: ['tenant_admin'] });

function releaseSettings(): IncidentCatalogue {
  const cat = fakeIncidentCatalogue();
  cat.closure_codes = [
    { code: 'completed', labels: null, disabled: false },
    { code: 'rolled_back', labels: null, disabled: false },
  ] as IncidentCatalogue['closure_codes'];
  return cat;
}

function routes(cat: IncidentCatalogue = releaseSettings()) {
  return {
    'GET /api/v1/releases/settings': { body: cat },
    'GET /api/v1/custom-fields': { body: [] },
  };
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

describe('Admin › Releases', () => {
  it('REQ-REL-050: lists the release closure codes and saves to the release settings', async () => {
    const saved = releaseSettings();
    saved.version = 2;
    const fake = api({
      me: ADMIN,
      routes: {
        ...routes(),
        'PUT /api/v1/releases/settings/lists/closure_code/order': { body: saved },
      },
    });
    open('/admin/releases');
    expect(await screen.findByTestId('list-closure_code-name-completed')).toBeTruthy();
    expect(screen.getByTestId('list-closure_code-name-rolled_back').textContent).toBe(
      'Rolled back',
    );
    fireEvent.click(screen.getByTestId('list-closure_code-down-completed'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/releases/settings/lists/closure_code/order')).toHaveLength(
        1,
      );
    });
    const [sent] = fake.find('PUT', '/api/v1/releases/settings/lists/closure_code/order');
    expect(sent?.body).toEqual({ codes: ['rolled_back', 'completed'] });
    // Never the incidents' settings.
    expect(fake.find('PUT', '/api/v1/incidents/settings/lists/closure_code/order')).toHaveLength(0);
  });

  it('REQ-REL-052: Closing lists the release kinds and has no auto-close block', async () => {
    const saved = releaseSettings();
    saved.version = 2;
    const fake = api({
      me: ADMIN,
      routes: { ...routes(), 'PATCH /api/v1/releases/settings/closure': { body: saved } },
    });
    open('/admin/releases/closing');
    expect(await screen.findByTestId('settings-open-work-linked_changes')).toBeTruthy();
    expect(screen.getByTestId('settings-open-work-child_releases')).toBeTruthy();
    expect(screen.queryByTestId('settings-open-work-child_incidents')).toBeNull();
    expect(screen.queryByTestId('settings-open-work-checklists')).toBeNull();
    // A release is neither auto-closed nor reopened by a reply.
    expect(screen.queryByTestId('settings-auto-close')).toBeNull();
    expect(screen.queryByTestId('settings-reopen-days')).toBeNull();
    // Its own words: never "incident".
    expect(screen.getByTestId('settings-closing').textContent).not.toMatch(/incident/i);
    fireEvent.click(screen.getByTestId('settings-complete-open-work'));
    fireEvent.click(screen.getByTestId('settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/releases/settings/closure')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/releases/settings/closure');
    expect(sent?.headers.get('If-Match')).toBe('"1"');
    expect(sent?.body).toMatchObject({ complete_open_work: true });
    // Only the release's own kinds are stored (lane A's review).
    expect(Object.keys((sent?.body as { open_work: object }).open_work).sort()).toEqual([
      'approvals',
      'child_releases',
      'linked_changes',
      'tasks',
    ]);
    expect(sent?.body).not.toHaveProperty('auto_close_days');
  });

  it('REQ-REL-051 AC1: only the close rule offers "Review completed"', async () => {
    const saved = releaseSettings();
    saved.version = 2;
    const fake = api({
      me: ADMIN,
      routes: { ...routes(), 'PATCH /api/v1/releases/settings/closure': { body: saved } },
    });
    open('/admin/releases/closing');
    const options = async (testId: string) => {
      const select = await screen.findByTestId(testId);
      const selector = select.querySelector('.ant-select-selector');
      if (selector === null) throw new Error('not an Ant Design Select');
      fireEvent.mouseDown(selector);
      return () =>
        [...document.querySelectorAll('.ant-select-item-option-content')].map((o) => o.textContent);
    };
    const close = await options('settings-close-requires');
    await waitFor(() => {
      expect(close()).toContain('Review completed');
    });
    const option = [...document.querySelectorAll('.ant-select-item-option-content')].find(
      (o) => o.textContent === 'Review completed',
    );
    if (option === undefined) throw new Error('no option');
    fireEvent.click(option);
    fireEvent.click(screen.getByTestId('settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/releases/settings/closure')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/releases/settings/closure');
    expect((sent?.body as { close_requires: string[] }).close_requires).toContain(
      'review_completed',
    );
  });

  it('REQ-REL-048: the stage tasks switch saves open_stage_tasks_block', async () => {
    const saved = releaseSettings();
    saved.version = 2;
    saved.open_stage_tasks_block = false;
    const fake = api({
      me: ADMIN,
      routes: { ...routes(), 'PATCH /api/v1/releases/settings': { body: saved } },
    });
    open('/admin/releases/stages');
    const toggle = await screen.findByTestId('settings-open-stage-tasks-block');
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(toggle);
    fireEvent.click(screen.getByTestId('settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/releases/settings')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/releases/settings');
    expect(sent?.body).toEqual({ open_stage_tasks_block: false });
  });

  it('REQ-REL-057 AC2: Roles says what Take makes you, and moves it on a click', async () => {
    const role = (code: string, take: boolean) => ({
      code,
      labels: null,
      description: null,
      single: true,
      eligibility: null,
      system: true,
      disabled: false,
      take,
    });
    const fake = api({
      me: ADMIN,
      routes: {
        ...routes(),
        'GET /api/v1/releases/settings/roles': {
          body: [role('release_manager', false), role('release_engineer', true)],
        },
        'PATCH /api/v1/releases/settings/roles/release_manager': { body: releaseSettings() },
      },
    });
    open('/admin/releases/roles');
    const engineer = await screen.findByTestId('settings-take-release_engineer');
    // Ant Design puts the test id on the radio's input.
    const input = engineer instanceof HTMLInputElement ? engineer : engineer.querySelector('input');
    expect(input?.checked).toBe(true);
    fireEvent.click(screen.getByTestId('settings-take-release_manager'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/releases/settings/roles/release_manager')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/releases/settings/roles/release_manager');
    expect(sent?.body).toEqual({ take: true });
    expect(sent?.headers.get('If-Match')).toBe('"1"');
  });

  it('is closed to people without the service desk configure right', async () => {
    api({
      me: fakeSession(
        { roles: ['technician'] },
        {
          permissions: [
            { key: 'releases.view', scope: 'all', scopes: ['all'], conditional: false },
          ],
        },
      ),
      routes: routes(),
    });
    open('/admin/releases/closing');
    expect(await screen.findByText(/permission/i)).toBeTruthy();
    expect(screen.queryByTestId('settings-closing')).toBeNull();
  });
});
