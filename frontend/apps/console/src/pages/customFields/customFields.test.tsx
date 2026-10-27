import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { CustomField } from '@supportx/api-client';
import {
  fakeCustomField,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi, problem } from '../../test/api';
import { rememberTab } from '../incidents/tabs';

// Custom fields (WP-026, REQ-INC-014): admin screen, create form, record properties, history
// labels and the list filter. Keys never show; labels do (AC3).

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ roles: ['tenant_admin'] });

const FLOOR: CustomField = fakeCustomField({
  id: 'cf-floor',
  key: 'affected_floor',
  field_type: 'choice',
  labels: { en: 'Affected floor', ar: 'الطابق المتأثر' },
  help: { en: 'Where the problem is' },
  choices: [
    { code: 'ground', labels: { en: 'Ground' }, retired: false },
    { code: 'first', labels: { en: 'First' }, retired: false },
    { code: 'old_wing', labels: { en: 'Old wing' }, retired: true },
  ],
  in_use: true,
});
const URGENT: CustomField = fakeCustomField({
  id: 'cf-urgent',
  key: 'urgent_call',
  field_type: 'yes_no',
  labels: { en: 'Urgent call' },
  sort_order: 1,
});
const ITEM = fakeIncident({ custom: { affected_floor: 'first', urgent_call: true } });
const PATH = `/api/v1/incidents/${ITEM.id}`;
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  'GET /api/v1/custom-fields': { body: [FLOOR, URGENT] },
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

describe('Admin › Incidents › Custom fields', () => {
  it('lists fields by label and type, never by key', async () => {
    api({ me: ADMIN, routes: COMMON });
    open('/admin/incidents/custom-fields');
    expect((await screen.findByTestId('cf-name-affected_floor')).textContent).toBe(
      'Affected floor',
    );
    const table = screen.getByTestId('settings-custom-fields');
    expect(within(table).getByText('Pick one')).toBeDefined();
    expect(within(table).getByText('Yes or no')).toBeDefined();
    expect(table.textContent).not.toContain('affected_floor');
  });

  it('adds a pick list with choices in each language', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'POST /api/v1/custom-fields': { status: 201, body: FLOOR },
      },
    });
    open('/admin/incidents/custom-fields');
    fireEvent.click(await screen.findByTestId('cf-new'));
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('cf-type')));
    fireEvent.click(
      (
        await screen.findAllByText('Pick one', { selector: '.ant-select-item-option-content' })
      )[0] as Element,
    );
    fireEvent.change(screen.getByTestId('cf-label-en'), { target: { value: 'Contract type' } });
    fireEvent.change(screen.getByTestId('cf-label-ar'), { target: { value: 'نوع العقد' } });
    fireEvent.click(screen.getByTestId('cf-choice-add'));
    fireEvent.change(await screen.findByTestId('cf-choice-name-en'), {
      target: { value: 'Gold' },
    });
    fireEvent.click(within(screen.getByTestId('cf-choice-dialog')).getByText('Add'));
    fireEvent.change(await screen.findByTestId('cf-choice-ar-0'), { target: { value: 'ذهبي' } });
    fireEvent.click(screen.getByTestId('cf-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/custom-fields')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/custom-fields')[0]?.body).toMatchObject({
      entity: 'incident',
      field_type: 'choice',
      labels: { en: 'Contract type', ar: 'نوع العقد' },
      choices: [{ code: null, labels: { en: 'Gold', ar: 'ذهبي' }, retired: false }],
      validation: { required: false, min: null, max: null, pattern: null },
      currency: null,
    });
  });

  it('shows the server problem in the editor, by field', async () => {
    api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'POST /api/v1/custom-fields': {
          status: 422,
          body: {
            ...problem(422, 'validation_failed'),
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
    open('/admin/incidents/custom-fields');
    fireEvent.click(await screen.findByTestId('cf-new'));
    fireEvent.change(await screen.findByTestId('cf-label-en'), { target: { value: 'Room' } });
    fireEvent.click(screen.getByTestId('cf-save'));
    // At the name, where it belongs (WP-026 QA BUG-08).
    expect((await screen.findByTestId('cf-error-labels')).textContent).toContain(
      'This name is already used.',
    );
  });

  it('REQ-INC-014 AC4 (D-087): a field in use asks first; Retire is the recommended answer', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'PATCH /api/v1/custom-fields/cf-floor': { body: { ...FLOOR, retired: true, version: 2 } },
        'DELETE /api/v1/custom-fields/cf-floor': { status: 204 },
      },
    });
    open('/admin/incidents/custom-fields');
    fireEvent.click(await screen.findByTestId('cf-remove-affected_floor'));
    const dialog = await screen.findByTestId('cf-remove-dialog');
    expect(dialog.textContent).toContain('Retiring it is recommended');
    const retire = screen.getByTestId('cf-retire-recommended');
    const remove = screen.getByTestId('cf-remove-ok');
    // Retire is the primary button; Remove is the secondary one.
    expect(retire.className).toContain('ant-btn-primary');
    expect(remove.className).not.toContain('ant-btn-primary');
    fireEvent.click(retire);
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/custom-fields/cf-floor')).toHaveLength(1);
    });
    expect(fake.find('PATCH', '/api/v1/custom-fields/cf-floor')[0]?.body).toEqual({
      retired: true,
    });
    expect(fake.find('DELETE', '/api/v1/custom-fields/cf-floor')).toHaveLength(0);

    // Removing anyway sends the confirmation.
    fireEvent.click(await screen.findByTestId('cf-remove-affected_floor'));
    fireEvent.click(await screen.findByTestId('cf-remove-ok'));
    await waitFor(() => {
      expect(fake.find('DELETE', '/api/v1/custom-fields/cf-floor')).toHaveLength(1);
    });
    const call = fake.find('DELETE', '/api/v1/custom-fields/cf-floor')[0];
    expect(call?.url.searchParams.get('confirm')).toBe('true');
    expect(call?.headers.get('If-Match')).toBe('"1"');
  });

  it('D-088: index progress shows live, and a failure says why with a retry', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let field: CustomField = { ...FLOOR, index_state: 'pending' };
    const fake = api({
      me: ADMIN,
      routes: {
        ...COMMON,
        'GET /api/v1/custom-fields': () => ({ body: [field] }),
        'POST /api/v1/custom-fields/cf-floor/index': () => ({
          body: { ...field, index_state: 'pending', index_error: null },
        }),
      },
    });
    open('/admin/incidents/custom-fields');
    expect((await screen.findByTestId('cf-index-affected_floor')).textContent).toBe(
      'Index pending',
    );
    field = { ...FLOOR, index_state: 'building', version: 2 };
    act(() => {
      realtime.publish(':broadcast', { type: 'metadata.custom_fields_changed', ids: [] });
    });
    await waitFor(() => {
      expect(screen.getByTestId('cf-index-affected_floor').textContent).toBe('Building index');
    });
    fireEvent.click(screen.getByTestId('cf-edit-affected_floor'));
    fireEvent.click(await screen.findByText('For integrations and performance'));
    field = { ...FLOOR, index_state: 'failed', index_error: 'busy', version: 3 };
    act(() => {
      realtime.publish(':broadcast', { type: 'metadata.custom_fields_changed', ids: [] });
    });
    expect((await screen.findByTestId('cf-index-failure')).textContent).toBe(
      'The index could not be built: The incidents table was busy with other maintenance. You can ask again.',
    );
    fireEvent.click(screen.getByTestId('cf-request-index'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/custom-fields/cf-floor/index')).toHaveLength(1);
    });
    expect(
      fake.find('POST', '/api/v1/custom-fields/cf-floor/index')[0]?.headers.get('If-Match'),
    ).toBe('"3"');
  });

  it('reloads the list live when another admin changes a field', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let fields = [FLOOR];
    api({
      me: ADMIN,
      routes: { ...COMMON, 'GET /api/v1/custom-fields': () => ({ body: fields }) },
    });
    open('/admin/incidents/custom-fields');
    await screen.findByTestId('cf-name-affected_floor');
    fields = [FLOOR, URGENT];
    act(() => {
      realtime.publish(':broadcast', { type: 'metadata.custom_fields_changed', ids: [] });
    });
    expect((await screen.findByTestId('cf-name-urgent_call')).textContent).toBe('Urgent call');
  });
});

describe('Custom fields on incidents', () => {
  it('the create form shows template fields, marks required ones and sends the values', async () => {
    const template = fakeIncidentTemplate({
      custom_fields: {
        affected_floor: {
          shown: true,
          required: true,
          requester_can_see: true,
          requester_can_fill: false,
        },
        urgent_call: {
          shown: false,
          required: false,
          requester_can_see: true,
          requester_can_fill: false,
        },
      },
    });
    const fake = api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents/templates': { body: [template] },
        'GET /api/v1/users': {
          body: {
            items: [{ id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' }],
            has_more: false,
            next_cursor: null,
          },
        },
        'POST /api/v1/incidents': { status: 201, body: ITEM },
        [`GET ${PATH}`]: { body: ITEM },
      },
    });
    open('/incidents/new');
    // Shown by its label and help; the hidden one is named as hidden; retired choices are not offered.
    expect(await screen.findByText('Affected floor')).toBeDefined();
    expect(screen.getByText('Where the problem is')).toBeDefined();
    expect(screen.queryByTestId('inc-custom-urgent_call')).toBeNull();
    expect(screen.getByTestId('inc-hidden-fields').textContent).toContain('Urgent call');
    fireEvent.change(screen.getByTestId('inc-subject'), { target: { value: 'Lights out' } });
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-requester')));
    fireEvent.click(await screen.findByText('rana@demo.test'));
    fireEvent.click(screen.getByTestId('inc-save'));
    expect((await screen.findByTestId('error-custom-affected_floor')).textContent).toBe(
      'This field is required.',
    );
    expect(fake.find('POST', '/api/v1/incidents')).toHaveLength(0);
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-custom-affected_floor')));
    expect(
      screen.queryAllByText('Old wing', { selector: '.ant-select-item-option-content' }),
    ).toHaveLength(0);
    fireEvent.click(
      (
        await screen.findAllByText('First', { selector: '.ant-select-item-option-content' })
      )[0] as Element,
    );
    fireEvent.click(screen.getByTestId('inc-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/incidents')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/incidents')[0]?.body).toMatchObject({
      custom: { affected_floor: 'first' },
    });
  });

  it('the record shows custom values by label and edits them in place', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
        [`PATCH ${PATH}`]: {
          body: { ...ITEM, custom: { affected_floor: 'ground', urgent_call: true }, version: 2 },
        },
        [`GET ${PATH}/history`]: {
          body: { items: [], has_more: false, next_cursor: null, people: {} },
        },
      },
    });
    // Start on the Details tab (the default is Conversation, D-081).
    rememberTab(fakeSession().user.id, 'details');
    open(`/incidents/${ITEM.id}`);
    expect((await screen.findByTestId('inc-prop-custom.affected_floor')).textContent).toBe('First');
    expect(screen.getByTestId('inc-prop-custom.urgent_call').textContent).toBe('Yes');
    fireEvent.click(screen.getByTestId('inc-edit-custom.affected_floor'));
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-input-custom.affected_floor')));
    fireEvent.click(
      (
        await screen.findAllByText('Ground', { selector: '.ant-select-item-option-content' })
      )[0] as Element,
    );
    fireEvent.click(screen.getByTestId('inc-save-custom.affected_floor'));
    await waitFor(() => {
      expect(fake.find('PATCH', PATH)).toHaveLength(1);
    });
    expect(fake.find('PATCH', PATH)[0]?.body).toMatchObject({
      custom: { affected_floor: 'ground' },
    });
  });

  it('REQ-INC-014 AC1: the list filters on a pick list field', async () => {
    const fake = api({
      routes: {
        ...COMMON,
        'GET /api/v1/incidents': {
          body: {
            items: [{ ...ITEM, deleted_at: null }],
            has_more: false,
            next_cursor: null,
            people: {},
            estimated_total: 1,
          },
        },
        'GET /api/v1/incidents/views': { body: [] },
        'GET /api/v1/incidents/counters': { body: [] },
      },
    });
    open('/incidents');
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-filter-custom-field')));
    fireEvent.click(
      (
        await screen.findAllByText('Affected floor', {
          selector: '.ant-select-item-option-content',
        })
      )[0] as Element,
    );
    fireEvent.mouseDown(selectorOf(await screen.findByTestId('inc-filter-custom-value')));
    fireEvent.click(
      (
        await screen.findAllByText('First', { selector: '.ant-select-item-option-content' })
      )[0] as Element,
    );
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/incidents').at(-1);
      expect(last?.url.searchParams.get('filter')).toBe(
        JSON.stringify({ field: 'custom.affected_floor', op: 'eq', value: 'first' }),
      );
    });
  });
});
