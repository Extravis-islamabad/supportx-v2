import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { IncidentCategory, IncidentTemplate } from '@supportx/api-client';
import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-020c QA findings (~/Desktop/qa-wp020c/QA-REPORT.md) and the review answers (D-086). Each
// test is named after its finding and failed before the fix.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const ADMIN_AR = fakeSession({ roles: ['tenant_admin'], locale: 'ar' });

function node(
  id: string,
  parent: string | null,
  level: number,
  code: string | null,
  name: string | null,
  disabled = false,
): IncidentCategory {
  return {
    id,
    parent_id: parent,
    level,
    code,
    labels: name === null ? null : { en: name },
    sort_order: 0,
    default_group_id: null,
    disabled,
    version: 1,
  };
}
const TREE = [
  node('c-hw', null, 1, 'hardware', null),
  node('c-net', null, 1, 'network', null),
  node('s-laptop', 'c-hw', 2, 'laptop_or_desktop', null),
  node('s-vpn', 'c-net', 2, 'vpn', null, true),
];
const VPN_TEMPLATE: IncidentTemplate = fakeIncidentTemplate({
  id: 't-vpn',
  code: null,
  labels: { en: 'VPN' },
  is_default: false,
  defaults: { category_id: 's-vpn' },
});
const PROBLEM = (field: string, code: string, params: Record<string, unknown> = {}) => ({
  status: 422,
  body: {
    type: 'about:blank',
    title: 'Validation failed',
    status: 422,
    code: 'validation_failed',
    message_key: 'errors.validation_failed',
    errors: [{ field: `body.${field}`, code, message_key: `errors.field.${code}`, params }],
  },
});
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate(), VPN_TEMPLATE] },
  'GET /api/v1/incidents/categories': { body: TREE },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/incidents/reply-templates': {
    body: [
      {
        id: 'rt-1',
        name: 'Restart',
        body: '<p>Restart it.</p>',
        version: 1,
        created_at: '2026-10-24T09:00:00Z',
        updated_at: '2026-10-24T09:00:00Z',
      },
    ],
  },
};

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
  setDefaultClientFactory(inertClientFactory);
  vi.restoreAllMocks();
});

describe('WP-020c QA findings', () => {
  it('BUG-01 + C1: numbering is one save, and its problem shows at the field it belongs to', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'PATCH /api/v1/incidents/settings': PROBLEM('next_number', 'number_already_used', {
          minimum: 8,
        }),
      },
    });
    open('/admin/incidents/general');
    fireEvent.change(await screen.findByTestId('settings-prefix'), { target: { value: 'QAT' } });
    const box = screen.getByTestId('settings-next-number');
    const next = box instanceof HTMLInputElement ? box : box.querySelector('input');
    if (next === null) throw new Error('no number input');
    fireEvent.change(next, { target: { value: '5' } });
    fireEvent.click(screen.getByTestId('settings-numbering-save'));
    expect((await screen.findByTestId('settings-numbering-error-next_number')).textContent).toBe(
      'That number is already used. Choose 8 or higher.',
    );
    expect(screen.queryByTestId('settings-numbering-error-prefix')).toBeNull();
    const calls = fake.find('PATCH', '/api/v1/incidents/settings');
    expect(calls).toHaveLength(1);
    expect(calls[0]?.body).toEqual({ prefix: 'QAT', next_number: 5 });
    expect(fake.find('PUT', '/api/v1/incidents/settings/numbering')).toHaveLength(0);
  });

  it('BUG-07: Reset clears the problem shown with it', async () => {
    api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'PATCH /api/v1/incidents/settings': PROBLEM('prefix', 'invalid_prefix'),
      },
    });
    open('/admin/incidents/general');
    fireEvent.change(await screen.findByTestId('settings-prefix'), { target: { value: 'Q1' } });
    fireEvent.click(screen.getByTestId('settings-numbering-save'));
    await screen.findByTestId('settings-numbering-error-prefix');
    fireEvent.click(within(screen.getByTestId('settings-numbering')).getByText('Reset'));
    await waitFor(() => {
      expect(screen.queryByTestId('settings-numbering-error-prefix')).toBeNull();
    });
  });

  it('BUG-02: your own save never shows "changed elsewhere"; somebody else\'s does', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let version = 1;
    api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/settings': () => ({ body: { ...fakeIncidentCatalogue(), version } }),
        'PATCH /api/v1/incidents/settings': () => {
          version += 1;
          return { body: { ...fakeIncidentCatalogue(), version } };
        },
      },
    });
    open('/admin/incidents/general');
    // Unsaved edit in the defaults card, then a save in the automation card.
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('settings-default-priority')));
    fireEvent.click(
      (
        await screen.findAllByText('P1 – Critical', { selector: '.ant-select-item-option-content' })
      )[0] as Element,
    );
    fireEvent.click(screen.getByTestId('settings-auto-status'));
    fireEvent.click(screen.getByTestId('settings-automation-save'));
    await screen.findByText('Saved. Open forms use the change at once.');
    act(() => {
      realtime.publish(':broadcast', { type: 'work_items.settings_changed', ids: [] });
    });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(screen.queryByTestId('settings-stale')).toBeNull();
    // Another admin's change (a version this tab did not make) is announced.
    version += 1;
    act(() => {
      realtime.publish(':broadcast', { type: 'work_items.settings_changed', ids: [] });
    });
    expect(await screen.findByTestId('settings-stale')).toBeDefined();
  });

  it('BUG-05: copying a template suggests a name in every language, in any UI language', async () => {
    api({ me: ADMIN_AR, routes: COMMON });
    open('/admin/incidents/templates');
    fireEvent.click(await screen.findByTestId(`tpl-admin-copy-${fakeIncidentTemplate().id}`));
    expect((await screen.findByTestId<HTMLInputElement>('tpl-copy-name-en')).value).toBe(
      'Standard incident (copy)',
    );
    expect(screen.getByTestId<HTMLInputElement>('tpl-copy-name-ar').value).toBe('حادث عادي (نسخة)');
    expect(screen.getByTestId<HTMLInputElement>('tpl-copy-name-ur').value).toBe(
      'معیاری واقعہ (نقل)',
    );
  });

  it('BUG-06: the category tree opens expanded once it has loaded', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/categories');
    expect(await screen.findByText('Laptop or desktop')).toBeDefined();
  });

  it('BUG-08: the template editor raises no React warnings', async () => {
    const errors = vi.spyOn(console, 'error');
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/templates');
    fireEvent.click(await screen.findByTestId('tpl-admin-new'));
    await screen.findByTestId('tpl-default-channel');
    expect(
      errors.mock.calls.filter((c) => String(c[0]).includes('should not be null')),
    ).toHaveLength(0);
  });

  it('BUG-09: name dialogs put the focus in their first field', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/levels');
    fireEvent.click(await screen.findByTestId('list-level-add'));
    const first = await screen.findByTestId('list-level-dialog-name-en');
    await waitFor(() => {
      expect(document.activeElement).toBe(first);
    });
  });

  it('C2: renaming starts from the built-in names, and an empty colour says so in our words', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/priority');
    fireEvent.click(await screen.findByTestId('scale-impact-edit-team'));
    const dialog = await screen.findByTestId('scale-impact-dialog');
    expect(dialog.textContent).not.toContain('Transparent');
    expect(dialog.textContent).toContain('No colour');
    fireEvent.click(within(dialog).getByTestId('scale-impact-dialog-shipped'));
    expect((await screen.findByTestId<HTMLInputElement>('scale-impact-dialog-name-en')).value).toBe(
      'A team',
    );
    expect(screen.getByTestId<HTMLInputElement>('scale-impact-dialog-name-ar').value).toBe('فريق');
  });

  it('C3: starting-value labels have no colon', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/templates');
    fireEvent.click(await screen.findByTestId('tpl-admin-new'));
    const label = (await screen.findByTestId('tpl-default-subject')).closest('.ant-form-item');
    expect(label?.querySelector('.ant-form-item-no-colon')).not.toBeNull();
  });

  it('C4: templates without a group are listed under a clear heading', async () => {
    api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/templates': {
          body: [fakeIncidentTemplate(), { ...VPN_TEMPLATE, group_name: 'Network', defaults: {} }],
        },
      },
    });
    open('/incidents/new');
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-template')));
    expect(await screen.findByText('Without a group')).toBeDefined();
    expect(screen.queryByText('Templates', { selector: '.ant-select-item-group' })).toBeNull();
  });

  it('C5: "Other" offers no Retire; it says why', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/reasons');
    const retire = await screen.findByTestId('list-pause-retire-other');
    expect(retire.hasAttribute('disabled')).toBe(true);
    expect(retire.getAttribute('aria-describedby') ?? retire.getAttribute('title')).toBeTruthy();
  });

  it('C7: reply templates: New in the card header; removing says what it does', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/reply-templates');
    const card = await screen.findByTestId('settings-reply-templates');
    expect(card.querySelector('.ant-card-extra [data-testid="tpl-new"]')).not.toBeNull();
    fireEvent.click(await within(card).findByText('Remove'));
    expect(await screen.findByText(/Replies already sent keep their text/)).toBeDefined();
  });

  it('C8: a record shows its retired category and level as retired', async () => {
    const catalogue = fakeIncidentCatalogue();
    const levels = catalogue.levels.map((v) =>
      v.code === 'tier_2' ? { ...v, disabled: true } : v,
    );
    const item = fakeIncident({ category_id: 's-vpn', level: 'tier_2' });
    api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/settings': { body: { ...catalogue, levels } },
        [`GET /api/v1/incidents/${item.id}`]: { body: item },
        [`GET /api/v1/incidents/${item.id}/followers`]: {
          body: { items: [], may_manage: true, people: {} },
        },
        'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
      },
    });
    open(`/incidents/${item.id}`);
    fireEvent.click(await screen.findByRole('tab', { name: 'Details' }));
    await waitFor(() => {
      expect(screen.getByTestId('inc-prop-category_id').textContent).toBe(
        'Network › VPN (retired)',
      );
    });
    expect(screen.getByTestId('inc-prop-level').textContent).toBe('Tier 2 (retired)');
  });

  it('C9: a retired starting subcategory falls back to its active category, and says so', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/incidents/new');
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-template')));
    fireEvent.click(
      (
        await screen.findAllByText('VPN', { selector: '.ant-select-item-option-content' })
      )[0] as Element,
    );
    await waitFor(() => {
      expect(screen.getByTestId('inc-category-category').textContent).toContain('Network');
    });
    expect(screen.getByTestId('inc-dropped-defaults').textContent).toContain('Category');
  });

  it('D-086: requester flags are locked on for subject and requester, with the reason', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/templates');
    fireEvent.click(await screen.findByTestId('tpl-admin-new'));
    for (const field of ['subject', 'requester_id']) {
      for (const flag of ['requester_can_see', 'requester_can_fill']) {
        const control = await screen.findByTestId(`tpl-rule-${field}-${flag}`);
        expect(control.className).toContain('ant-switch-disabled');
        expect(control.getAttribute('aria-checked')).toBe('true');
      }
    }
    expect(screen.getByTestId('tpl-editor-locked-note').textContent).toContain(
      'requesters could not log',
    );
  });
});
