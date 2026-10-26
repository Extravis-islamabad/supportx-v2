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
import { consoleApi, ME_PATH } from '../../../test/api';

// WP-020c: incident settings screens, templates on the create form, the 3-level category
// picker, Level, Impact details and the compact form layout. Test names cite the requirement.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ roles: ['tenant_admin'] });

function node(
  id: string,
  parent: string | null,
  level: number,
  name: string,
  disabled = false,
): IncidentCategory {
  return {
    id,
    parent_id: parent,
    level,
    code: null,
    labels: { en: name },
    sort_order: 0,
    default_group_id: null,
    disabled,
    version: 1,
  };
}
const TREE = [
  node('c-hw', null, 1, 'Hardware'),
  node('c-net', null, 1, 'Network'),
  node('c-old', null, 1, 'Mainframe', true),
  node('s-printer', 'c-hw', 2, 'Printer'),
  node('s-laptop', 'c-hw', 2, 'Laptop'),
  node('s-vpn', 'c-net', 2, 'VPN'),
  node('i-toner', 's-printer', 3, 'Toner'),
];
const OUTAGE: IncidentTemplate = fakeIncidentTemplate({
  id: 't-outage',
  code: null,
  labels: { en: 'Network outage', ar: 'انقطاع الشبكة' },
  is_default: false,
  group_name: 'Infrastructure',
  fields: {
    ...fakeIncidentTemplate().fields,
    tags: { shown: false, required: false, requester_can_see: false, requester_can_fill: false },
    impact_details: {
      shown: true,
      required: true,
      requester_can_see: true,
      requester_can_fill: true,
    },
  },
  defaults: { category_id: 'c-net', urgency: 'high' },
});
// Hides impact details: switching to it after typing them must ask first.
const QUICK: IncidentTemplate = fakeIncidentTemplate({
  id: 't-quick',
  code: null,
  labels: { en: 'Quick call' },
  is_default: false,
  fields: {
    ...fakeIncidentTemplate().fields,
    impact_details: {
      shown: false,
      required: false,
      requester_can_see: false,
      requester_can_fill: false,
    },
  },
});
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate(), OUTAGE, QUICK] },
  'GET /api/v1/incidents/categories': { body: TREE },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/incidents/reply-templates': { body: [] },
};

function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}

/** Open an Ant Design Select (once it is enabled) and click the option showing `option`. */
async function choose(testId: string, option: string) {
  const select = await screen.findByTestId(testId);
  await waitFor(() => {
    expect(select.className).not.toContain('ant-select-disabled');
  });
  fireEvent.mouseDown(selectorOf(select));
  let found: Element | undefined;
  await waitFor(() => {
    const options = [...document.querySelectorAll('.ant-select-item-option-content')].filter(
      (o) => o.textContent === option,
    );
    found = options[options.length - 1];
    expect(found).toBeDefined();
  });
  if (found !== undefined) fireEvent.click(found);
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
  vi.useRealTimers();
});

describe('WP-020c: templates on the new incident form', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents/new');
  });

  it('REQ-INC-017 AC1: the default template is preselected and the picker is searchable and grouped', async () => {
    api({ routes: COMMON });
    render(<App />);
    const picker = await screen.findByTestId('inc-template');
    await waitFor(() => {
      expect(picker.textContent).toContain('Standard incident');
    });
    fireEvent.mouseDown(selectorOf(picker));
    expect(await screen.findByText('Infrastructure')).toBeDefined();
    expect(
      screen.getByText('Network outage', { selector: '.ant-select-item-option-content' }),
    ).toBeDefined();
  });

  it('REQ-INC-035 AC1: switching fills untouched fields, keeps typed ones, lists hidden fields', async () => {
    api({ routes: COMMON });
    render(<App />);
    fireEvent.change(await screen.findByTestId('inc-subject'), {
      target: { value: 'Office offline' },
    });
    await choose('inc-template', 'Network outage');
    // Starting values arrive in untouched fields; what was typed stays.
    await waitFor(() => {
      expect(screen.getByTestId('inc-category-category').textContent).toContain('Network');
      expect(screen.getByTestId('inc-urgency').textContent).toContain('High');
    });
    expect(screen.getByTestId<HTMLInputElement>('inc-subject').value).toBe('Office offline');
    // Nothing hidden without saying so; required markers follow the template.
    expect(screen.getByTestId('inc-hidden-fields').textContent).toContain('Tags');
    expect(screen.queryByTestId('inc-tags')).toBeNull();
  });

  it('REQ-INC-035: switching asks before clearing a filled field the new template hides', async () => {
    api({ routes: COMMON });
    render(<App />);
    fireEvent.change(await screen.findByTestId('inc-impact-details'), {
      target: { value: 'Whole floor' },
    });
    await choose('inc-template', 'Quick call');
    const dialog = await screen.findByTestId('inc-template-switch');
    expect(dialog.textContent).toContain('Impact details');
    // Keep: nothing changes.
    fireEvent.click(within(dialog).getByText('Keep this template'));
    await waitFor(() => {
      expect(screen.getByTestId('inc-template').textContent).toContain('Standard incident');
    });
    expect(screen.getByTestId<HTMLTextAreaElement>('inc-impact-details').value).toBe('Whole floor');
    // Switch: the hidden field is cleared, the switch happens.
    await choose('inc-template', 'Quick call');
    fireEvent.click(
      within(await screen.findByTestId('inc-template-switch')).getByText('Switch and clear them'),
    );
    await waitFor(() => {
      expect(screen.getByTestId('inc-template').textContent).toContain('Quick call');
    });
    expect(screen.queryByTestId('inc-impact-details')).toBeNull();
    expect(screen.getByTestId('inc-hidden-fields').textContent).toContain('Impact details');
  });

  it("REQ-INC-035: the template's required fields are checked before sending", async () => {
    const fake = api({ routes: COMMON });
    render(<App />);
    await choose('inc-template', 'Network outage');
    fireEvent.change(await screen.findByTestId('inc-subject'), { target: { value: 'Down' } });
    fireEvent.click(screen.getByTestId('inc-save'));
    expect((await screen.findByTestId('error-impact_details')).textContent).toBe(
      'This field is required.',
    );
    expect(fake.find('POST', '/api/v1/incidents')).toHaveLength(0);
  });

  it('sends the template, Level and Impact details with the new incident', async () => {
    const created = fakeIncident();
    const fake = api({
      routes: {
        ...COMMON,
        'GET /api/v1/users': {
          body: {
            items: [{ id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' }],
            has_more: false,
            next_cursor: null,
          },
        },
        'POST /api/v1/incidents': { status: 201, body: created },
        [`GET /api/v1/incidents/${created.id}`]: { body: created },
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByTestId('inc-subject'), { target: { value: 'Down' } });
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-requester')));
    fireEvent.click(await screen.findByText('rana@demo.test'));
    await choose('inc-level', 'Tier 2');
    fireEvent.change(screen.getByTestId('inc-impact-details'), {
      target: { value: 'Second floor' },
    });
    fireEvent.click(screen.getByTestId('inc-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/incidents')).toHaveLength(1);
    });
    const body = fake.find('POST', '/api/v1/incidents')[0]?.body as Record<string, unknown>;
    expect(body).toMatchObject({
      template_id: fakeIncidentTemplate().id,
      level: 'tier_2',
      impact_details: 'Second floor',
    });
  });
});

describe('REQ-INC-006: category, subcategory and item', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents/new');
  });

  it('AC1-AC4: dependent pickers, clearing with a notice, retired not offered, search all levels', async () => {
    api({ routes: COMMON });
    render(<App />);
    const sub = await screen.findByTestId('inc-category-subcategory');
    // AC1: no subcategory before a category.
    expect(sub.className).toContain('ant-select-disabled');
    await choose('inc-category-category', 'Hardware');
    // AC3: the retired category is not offered.
    expect(
      screen.queryByText('Mainframe', { selector: '.ant-select-item-option-content' }),
    ).toBeNull();
    await choose('inc-category-subcategory', 'Printer');
    await choose('inc-category-item', 'Toner');
    // AC2: another category clears subcategory and item, and says so.
    await choose('inc-category-category', 'Network');
    expect((await screen.findByTestId('inc-category-notice')).textContent).toContain(
      'Subcategory and item were cleared',
    );
    expect(screen.getByTestId('inc-category-subcategory').textContent).not.toContain('Printer');
    // AC4: search at any level.
    fireEvent.click(screen.getByTestId('inc-category-search-open'));
    const search = await screen.findByTestId('inc-category-search');
    const input = search.querySelector('input');
    if (input === null) throw new Error('no search input');
    fireEvent.change(input, { target: { value: 'Ton' } });
    fireEvent.click(
      await screen.findByText('Hardware › Printer › Toner', {
        selector: '.ant-select-item-option-content',
      }),
    );
    await waitFor(() => {
      expect(screen.getByTestId('inc-category-item').textContent).toContain('Toner');
    });
  });

  it('AC3: an old record keeps its retired category, marked', async () => {
    const item = fakeIncident({ category_id: 'c-old' });
    api({
      routes: {
        ...COMMON,
        [`GET /api/v1/incidents/${item.id}`]: { body: item },
        [`GET /api/v1/incidents/${item.id}/followers`]: {
          body: { items: [], may_manage: true, people: {} },
        },
        'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
      },
    });
    window.history.pushState({}, '', `/incidents/${item.id}`);
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Details' }));
    await waitFor(() => {
      expect(screen.getByTestId('inc-prop-category_id').textContent).toContain('Mainframe');
    });
  });
});

describe('form density (user preference)', () => {
  it('compact puts labels on the left and is saved with the user', async () => {
    const fake = api({ routes: { ...COMMON, [`PATCH ${ME_PATH}`]: { body: {} } } });
    window.history.pushState({}, '', '/incidents/new');
    render(<App />);
    const form = await screen.findByTestId('inc-form');
    expect(form.getAttribute('data-density')).toBe('comfortable');
    fireEvent.click(within(screen.getByTestId('inc-density')).getByText('Compact'));
    await waitFor(() => {
      expect(screen.getByTestId('inc-form').getAttribute('data-density')).toBe('compact');
    });
    expect(screen.getByTestId('inc-form').className).toContain('ant-form-horizontal');
    await waitFor(() => {
      expect(fake.find('PATCH', ME_PATH)[0]?.body).toEqual({ form_density: 'compact' });
    });
  });
});

describe('Admin › Incidents', () => {
  it('is offered to settings admins only', async () => {
    api({ routes: COMMON });
    window.history.pushState({}, '', '/admin/incidents/general');
    render(<App />);
    await waitFor(() => {
      expect(document.querySelector('.ant-result-403')).not.toBeNull();
    });
    expect(screen.queryByTestId('settings-sections')).toBeNull();
  });

  it('REQ-INC-009 AC4: the matrix is saved whole with the version shown, then used at once', async () => {
    const saved = fakeIncidentCatalogue();
    const fake = api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'PUT /api/v1/incidents/settings/matrix': { body: { ...saved, version: 2 } },
      },
    });
    window.history.pushState({}, '', '/admin/incidents/priority');
    render(<App />);
    await choose('matrix-one_person-critical', 'P1 – Critical');
    fireEvent.click(screen.getByTestId('matrix-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/incidents/settings/matrix')).toHaveLength(1);
    });
    const call = fake.find('PUT', '/api/v1/incidents/settings/matrix')[0];
    expect(call?.headers.get('If-Match')).toBe('"1"');
    const cells = (call?.body as { cells: { impact: string; urgency: string; priority: string }[] })
      .cells;
    expect(cells).toHaveLength(16);
    expect(cells.find((c) => c.impact === 'one_person' && c.urgency === 'critical')?.priority).toBe(
      'p1',
    );
  });

  it('REQ-ADM-043: a pick list value is added and its problems are shown in the dialog', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'POST /api/v1/incidents/settings/lists/level/values': {
          status: 422,
          body: {
            type: 'about:blank',
            title: 'Validation failed',
            status: 422,
            code: 'validation_failed',
            message_key: 'errors.validation_failed',
            errors: [
              {
                field: 'body.labels',
                code: 'duplicate_name',
                message_key: 'errors.field.duplicate_name',
                params: {},
              },
            ],
          },
        },
      },
    });
    window.history.pushState({}, '', '/admin/incidents/levels');
    render(<App />);
    fireEvent.click(await screen.findByTestId('list-level-add'));
    fireEvent.change(await screen.findByTestId('list-level-dialog-name-en'), {
      target: { value: 'Tier 1' },
    });
    fireEvent.click(screen.getByText('Save'));
    expect((await screen.findByTestId('list-level-dialog-problems')).textContent).not.toBe('');
    expect(fake.find('POST', '/api/v1/incidents/settings/lists/level/values')[0]?.body).toEqual({
      labels: { en: 'Tier 1' },
      colour: null,
    });
  });

  it('REQ-INC-035: the template editor never allows a contradictory field rule', async () => {
    api({ me: ADMIN, routes: COMMON });
    window.history.pushState({}, '', '/admin/incidents/templates');
    render(<App />);
    fireEvent.click(await screen.findByTestId('tpl-admin-new'));
    // Subject is locked shown + required.
    const subjectRequired = await screen.findByTestId('tpl-rule-subject-required');
    expect(subjectRequired.className).toContain('ant-switch-disabled');
    // Hiding then requiring a field shows it again; requester fill implies requester see.
    fireEvent.click(screen.getByTestId('tpl-rule-tags-shown'));
    expect(screen.getByTestId('tpl-rule-tags-shown').getAttribute('aria-checked')).toBe('false');
    fireEvent.click(screen.getByTestId('tpl-rule-tags-required'));
    expect(screen.getByTestId('tpl-rule-tags-shown').getAttribute('aria-checked')).toBe('true');
    fireEvent.click(screen.getByTestId('tpl-rule-tags-requester_can_see'));
    fireEvent.click(screen.getByTestId('tpl-rule-tags-requester_can_fill'));
    expect(screen.getByTestId('tpl-rule-tags-requester_can_see').getAttribute('aria-checked')).toBe(
      'true',
    );
  });

  it('settings changed by another admin reach open screens live', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const fake = api({ me: ADMIN, routes: COMMON });
    window.history.pushState({}, '', '/admin/incidents/statuses');
    render(<App />);
    await screen.findByTestId('settings-statuses');
    const before = fake.find('GET', '/api/v1/incidents/settings').length;
    act(() => {
      realtime.publish(':broadcast', { type: 'work_items.settings_changed', ids: [] });
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/incidents/settings').length).toBeGreaterThan(before);
    });
  });
});
