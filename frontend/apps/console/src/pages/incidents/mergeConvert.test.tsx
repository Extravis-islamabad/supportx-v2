import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  type FakeRoute,
  fakeCustomField,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  problem,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { clickAction } from '../../test/actions';
import { consoleApi, fakeSession } from '../../test/api';
import { rememberTab } from './tabs';

// WP-046b S2 in the console: merge with a preview and a confirmation (REQ-INC-088), the banner
// on a merged or converted record with undo (REQ-INC-150), converting (REQ-INC-089) and an old
// number leading to the record it became.

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ITEM = fakeIncident();
const OTHER = fakeIncident({
  id: '01900000-0000-7000-8000-00000000c008',
  display_id: 'INC-8',
  subject: 'Printer toner is low',
});
const PATH = `/api/v1/incidents/${ITEM.id}`;

const PREVIEW = {
  duplicate_id: ITEM.id,
  into_id: OTHER.id,
  child_ids: ['01900000-0000-7000-8000-00000000c101'],
  followers_added: [],
  followers_not_added: ['01900000-0000-7000-8000-0000000002a1'],
  staff_newly_seeing: 3,
  requesters_newly_seeing: 0,
  followers_newly_seeing: 0,
  audience_complete: true,
  needs_confirmation: true,
};

function routes(extra: Record<string, FakeRoute> = {}, item = ITEM) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/custom-fields': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    'GET /api/v1/incidents/search': { body: { items: [OTHER], people: {} } },
    [`GET ${PATH}`]: { body: item, headers: { ETag: `"${String(item.version)}"` } },
    [`GET ${PATH}/conversation`]: { body: { items: [], people: {} } },
    ...extra,
  };
}

let restore: () => void = () => undefined;
beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  rememberTab(ADMIN.user.id, 'details');
});
afterEach(() => {
  restore();
});

describe('Merge an incident', () => {
  it('previews what moves and who would newly see it, and merges only once confirmed', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: routes({
        [`GET ${PATH}/merge-preview`]: { body: PREVIEW },
        [`POST ${PATH}/merge`]: {
          body: { id: ITEM.id, status: 'merged', version: ITEM.version + 1, moved_child_ids: [] },
        },
      }),
    });
    restore = fake.restore;
    render(<App />);
    await clickAction('inc-op-merge');
    const dialog = await screen.findByTestId('inc-merge-dialog');
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: 'The incident to keep' }));
    fireEvent.click(await screen.findByTestId('inc-merge-into-option-INC-8'));
    // Counts in words, never IDs: the children that move, staff newly seeing, not added.
    expect(await screen.findByText('Child incidents that move: 1')).toBeTruthy();
    expect(screen.getByText('Staff who would newly see this incident: 3')).toBeTruthy();
    expect(
      screen.getByText('Requesters not added as followers (another department): 1'),
    ).toBeTruthy();
    const confirm = screen.getByTestId('inc-merge-confirm');
    expect(confirm.hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByTestId('inc-merge-wider-ok'));
    await waitFor(() => {
      expect(screen.getByTestId('inc-merge-confirm').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('inc-merge-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/merge`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `${PATH}/merge`);
    expect(sent?.body).toEqual({ into_id: OTHER.id, confirm_wider_audience: true });
    expect(sent?.headers.get('If-Match')).toBe(`"${String(ITEM.version)}"`);
  });

  it('says where a merged incident went and offers undo', async () => {
    const merged = { ...ITEM, status: 'merged', status_category: 'closed' as const };
    const fake = consoleApi({
      me: ADMIN,
      routes: routes(
        {
          [`GET ${PATH}/links`]: {
            body: [
              {
                id: 'l-1',
                kind: 'merged_into',
                relation: 'merged_into',
                other_id: OTHER.id,
                other_type: 'incident',
                other_display_id: 'INC-8',
                other_subject: OTHER.subject,
                other_known_error: false,
                version: 1,
              },
            ],
          },
          [`POST ${PATH}/undo-merge`]: {
            body: { id: ITEM.id, status: 'new', version: ITEM.version + 1, moved_child_ids: [] },
          },
        },
        merged,
      ),
    });
    restore = fake.restore;
    render(<App />);
    const banner = await screen.findByTestId('inc-moved');
    await waitFor(() => {
      expect(within(banner).getByTestId('inc-moved-link').textContent).toContain('INC-8');
    });
    expect(banner.textContent).toContain('This incident was merged into');
    fireEvent.click(within(banner).getByTestId('inc-undo-merge'));
    // Asked first: nothing is sent until the undo is confirmed (lane C).
    expect(
      await screen.findByText(`Put ${ITEM.display_id} back as it was before the merge?`),
    ).toBeTruthy();
    expect(fake.find('POST', `${PATH}/undo-merge`)).toHaveLength(0);
    fireEvent.click(await screen.findByTestId('inc-undo-merge-ok'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/undo-merge`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${PATH}/undo-merge`)[0]?.headers.get('If-Match')).toBe(
      `"${String(ITEM.version)}"`,
    );
  });
});

describe('Merge when the audience grew meanwhile', () => {
  it('says the counts changed and asks for the tick again', async () => {
    let previews = 0;
    let merges = 0;
    const fake = consoleApi({
      me: ADMIN,
      routes: routes({
        [`GET ${PATH}/merge-preview`]: () => {
          previews += 1;
          return { body: { ...PREVIEW, staff_newly_seeing: previews === 1 ? 3 : 4 } };
        },
        [`POST ${PATH}/merge`]: () => {
          merges += 1;
          return {
            status: 409,
            body: problem(409, 'merge_widens_audience', {
              params: { staff: '4', requesters: '0', followers: '0', complete: 'true' },
            }),
          };
        },
      }),
    });
    restore = fake.restore;
    render(<App />);
    await clickAction('inc-op-merge');
    const dialog = await screen.findByTestId('inc-merge-dialog');
    fireEvent.mouseDown(within(dialog).getByRole('combobox', { name: 'The incident to keep' }));
    fireEvent.click(await screen.findByTestId('inc-merge-into-option-INC-8'));
    fireEvent.click(await screen.findByTestId('inc-merge-wider-ok'));
    fireEvent.click(screen.getByTestId('inc-merge-confirm'));
    expect(await screen.findByTestId('inc-merge-changed')).toBeTruthy();
    expect(await screen.findByText('Staff who would newly see this incident: 4')).toBeTruthy();
    expect(screen.getByTestId('inc-merge-confirm').hasAttribute('disabled')).toBe(true);
    expect(merges).toBe(1);
  });
});

describe('Convert an incident', () => {
  it('says why when the server refuses the preview', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: routes({
        [`GET ${PATH}/convert-preview`]: {
          status: 409,
          body: problem(409, 'record_closed'),
        },
        'GET /api/v1/catalog/items': { body: [] },
      }),
    });
    restore = fake.restore;
    render(<App />);
    await clickAction('inc-op-convert');
    const refused = await screen.findByTestId('inc-convert-refused');
    expect(refused.textContent).toContain('Closed and cancelled records cannot be changed.');
    expect(screen.getByTestId('inc-convert-confirm').hasAttribute('disabled')).toBe(true);
  });

  it('lists the fields left behind by name and sends the chosen catalog item', async () => {
    const cost = fakeCustomField({ key: 'cost_code', labels: { en: 'Cost code' } });
    const fake = consoleApi({
      me: ADMIN,
      routes: routes({
        'GET /api/v1/custom-fields': { body: [cost] },
        [`GET ${PATH}/convert-preview`]: {
          body: {
            record_id: ITEM.id,
            to_type: 'service_request',
            carried_custom: [],
            not_carried: ['cost_code'],
            pending_approvals: true,
          },
        },
        'GET /api/v1/catalog/items': {
          body: [{ id: 'item-1', names: { en: 'New laptop' }, questions: [] }],
        },
        'GET /api/v1/catalog/items/item-1': {
          body: { id: 'item-1', names: { en: 'New laptop' }, questions: [] },
        },
        [`POST ${PATH}/convert`]: {
          body: {
            old_id: ITEM.id,
            old_version: ITEM.version + 1,
            new_id: 'sr-1',
            new_display_id: 'SR-4',
            new_type: 'service_request',
            not_carried: ['cost_code'],
          },
        },
      }),
    });
    restore = fake.restore;
    render(<App />);
    await clickAction('inc-op-convert');
    const left = await screen.findByTestId('inc-convert-left');
    await waitFor(() => {
      expect(left.textContent).toContain('Cost code');
    });
    expect(left.textContent).not.toContain('cost_code'); // a name, never the key
    expect(screen.getByTestId('inc-convert-approvals')).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Catalog item' }));
    fireEvent.click(await screen.findByTitle('New laptop'));
    await waitFor(() => {
      expect(screen.getByTestId('inc-convert-confirm').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('inc-convert-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/convert`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${PATH}/convert`)[0]?.body).toEqual({
      catalog_item_id: 'item-1',
      answers: {},
      template_id: null,
    });
    await waitFor(() => {
      expect(window.location.pathname).toBe('/requests/sr-1');
    });
  });
});

describe('An old number', () => {
  it('leads to the record it became, from the command palette', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: routes({
        'GET /api/v1/incidents/search': { body: { items: [], people: {} } },
        'GET /api/v1/incidents/alias/INC-3': {
          body: { record_type: 'service_request', record_id: 'sr-9', display_id: 'SR-9' },
        },
      }),
    });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('user-name');
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = await screen.findByRole('combobox', { name: 'Type a page name…' });
    fireEvent.change(input, { target: { value: 'inc-3' } });
    const option = await screen.findByText('INC-3 is now SR-9.');
    fireEvent.click(option);
    await waitFor(() => {
      expect(window.location.pathname).toBe('/requests/sr-9');
    });
  });
});
