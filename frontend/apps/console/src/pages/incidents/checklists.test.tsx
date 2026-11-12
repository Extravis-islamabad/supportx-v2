import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { rememberTab } from './tabs';

// WP-046a S2 on the incident record: checklists (REQ-INC-040, -077), all files with a zip of the
// picked ones (REQ-INC-080) and your own reminders (REQ-INC-082). Every write carries the
// version it read; reminders are only ever yours.

const SESSION_USER = '01900000-0000-7000-8000-000000000101';
const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;
const LIST_ID = '01a1a2b3-0000-7000-8000-00000000c101';
const ITEM_ID = '01a1a2b3-0000-7000-8000-00000000c201';
const FILE_A = '01a1a2b3-0000-7000-8000-00000000f001';
const FILE_B = '01a1a2b3-0000-7000-8000-00000000f002';

const checklist = {
  id: LIST_ID,
  title: 'Before the switch swap',
  position: 0,
  library_id: null,
  items: [
    {
      id: ITEM_ID,
      text: 'Save the running configuration',
      position: 0,
      done_at: null,
      done_by: null,
      version: 2,
    },
  ],
  done: 0,
  total: 1,
  version: 1,
};

function file(id: string, name: string, openable = true) {
  return {
    id,
    name,
    size: 2048,
    content_type: 'application/pdf',
    created_at: '2026-11-11T09:00:00Z',
    has_thumbnail: false,
    inline: false,
    kind: 'document',
    openable,
    owner_id: ITEM.id,
    owner_type: 'work_item',
    previewable: false,
    record_id: ITEM.id,
    record_type: 'incident',
    state: openable ? 'clean' : 'infected',
    uploaded_by: SESSION_USER,
    version: 1,
  };
}

const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  [`GET ${PATH}`]: { body: ITEM, headers: { ETag: `"${String(ITEM.version)}"` } },
  [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null, people: {} } },
  [`GET ${PATH}/checklists`]: { body: [checklist] },
  'GET /api/v1/incidents/checklist-library': { body: [] },
  [`GET ${PATH}/reminders`]: { body: [] },
  'GET /api/v1/my-reminders': { body: [] },
  [`GET /api/v1/files/records/incident/${ITEM.id}`]: {
    body: [file(FILE_A, 'report.pdf'), file(FILE_B, 'bad.exe', false)],
  },
};

let restore: () => void = () => undefined;
function api(routes: Record<string, unknown> = {}) {
  const fake = consoleApi({ routes: { ...COMMON, ...routes } as never });
  restore = fake.restore;
  return fake;
}

describe('WP-046a S2 on the incident record', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  });
  afterEach(() => {
    restore();
    localStorage.clear();
  });

  it('REQ-INC-077: a checklist shows its progress and a tick sends the item version it read', async () => {
    rememberTab(SESSION_USER, 'checklists');
    const fake = api({
      [`PATCH ${PATH}/checklist-items/${ITEM_ID}`]: {
        body: { ...checklist.items[0], done_at: '2026-11-11T10:00:00Z', version: 3 },
      },
    });
    render(<App />);
    const card = await screen.findByTestId('checklist-0');
    expect(card.textContent).toContain('0 of 1 done');
    fireEvent.click(within(card).getByRole('checkbox'));
    await waitFor(() => {
      expect(fake.find('PATCH', `${PATH}/checklist-items/${ITEM_ID}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `${PATH}/checklist-items/${ITEM_ID}`);
    expect(sent?.headers.get('If-Match')).toBe('"2"');
    expect(sent?.body).toEqual({ done: true });
  });

  it('REQ-INC-080: only openable files can be picked, and the zip asks for the picked ones', async () => {
    rememberTab(SESSION_USER, 'files');
    const fake = api({
      [`POST /api/v1/files/records/incident/${ITEM.id}/archive`]: {
        body: 'PK',
        headers: {
          'Content-Type': 'application/zip',
          'Content-Disposition': 'attachment; filename="incident-files.zip"',
        },
      },
    });
    const saved: string[] = [];
    const created = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:zip');
    const revoked = vi.spyOn(URL, 'revokeObjectURL').mockReturnValue(undefined);
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved.push(this.download);
    });
    try {
      render(<App />);
      const blocked = await screen.findByTestId(`all-file-${FILE_B}`);
      expect(within(blocked).getByRole('checkbox')).toHaveProperty('disabled', true);
      fireEvent.click(screen.getByTestId('all-files-select-all'));
      fireEvent.click(screen.getByTestId('all-files-download'));
      await waitFor(() => {
        expect(saved).toEqual(['incident-files.zip']);
      });
      const [sent] = fake.find('POST', `/api/v1/files/records/incident/${ITEM.id}/archive`);
      expect(sent?.body).toEqual({ file_ids: [FILE_A], language: 'en' });
    } finally {
      created.mockRestore();
      revoked.mockRestore();
      clicked.mockRestore();
    }
  });

  it('REQ-INC-082: a reminder is set with its note, time and alert', async () => {
    const fake = api({
      [`POST ${PATH}/reminders`]: { status: 201, body: {} },
    });
    render(<App />);
    const panel = await screen.findByTestId('record-reminders');
    expect(panel.textContent).toContain('You have no reminders on this record.');
    expect(within(panel).getByTestId('reminder-add-button')).toHaveProperty('disabled', true);
    fireEvent.change(within(panel).getByTestId('reminder-note'), {
      target: { value: 'Call the vendor back' },
    });
    expect(fake.find('POST', `${PATH}/reminders`)).toHaveLength(0);
  });
});
