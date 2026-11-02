import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  type FakeRoute,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// Suggestions while logging an incident (REQ-INC-021, REQ-KB-062, WP-034 s1, D-125).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ITEM = fakeIncident();

function selectorOf(select: HTMLElement): Element {
  const found = select.querySelector('.ant-select-selector');
  if (found === null) throw new Error('not an Ant Design Select');
  return found;
}
const ARTICLE_ID = '01900000-0000-7000-8000-00000000b001';
const SUGGESTION = {
  id: ARTICLE_ID,
  display_id: 'KB-1',
  topic_id: '01900000-0000-7000-8000-00000000c001',
  type_code: 'how_to',
  language: 'en',
  title: 'Clear a printer jam',
  status: 'published',
  review_on: null,
  updated_at: '2026-11-02T08:00:00Z',
  owner_id: '01900000-0000-7000-8000-000000000101',
  expired: false,
  withdrawn: false,
  review_due: false,
  snippet: [
    { text: 'Open the ', mark: false },
    { text: 'printer', mark: true },
    { text: ' tray.', mark: false },
  ],
};
const SETTINGS = (on: boolean) => ({
  prefix: 'KB',
  next_number: 2,
  self_approval: false,
  requesters_enabled: true,
  suggest_on_technician_form: on,
  version: 1,
});

function open(suggest: boolean, extra: Record<string, FakeRoute> = {}) {
  window.history.pushState({}, '', '/incidents/new');
  const fake = consoleApi({
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
      'GET /api/v1/knowledge/settings': { body: SETTINGS(suggest) },
      'GET /api/v1/knowledge/suggestions': { body: [SUGGESTION] },
      'GET /api/v1/users': {
        body: {
          items: [{ id: 'u-1', display_name: 'Rana Requester', email: 'rana@demo.test' }],
          has_more: false,
          next_cursor: null,
        },
      },
      'POST /api/v1/incidents': { status: 201, body: ITEM },
      [`GET /api/v1/incidents/${ITEM.id}`]: { body: ITEM },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('Suggestions on the new incident form (REQ-INC-021)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents/new');
  });

  it('suggests as the subject is typed, marks the matched words, and links the chosen article after the create', async () => {
    const fake = open(true, {
      [`POST /api/v1/knowledge/articles/${ARTICLE_ID}/links`]: {
        status: 201,
        body: { link_id: 'l-1', source: 'suggestion' },
      },
    });
    render(<App />);
    const panel = await screen.findByTestId('kb-suggestions');
    expect(panel.textContent).toContain('Type a few words');
    fireEvent.change(screen.getByTestId('inc-subject'), { target: { value: 'printer jammed' } });
    const row = await screen.findByTestId(`kb-suggestion-${ARTICLE_ID}`, {}, { timeout: 3000 });
    expect(within(row).getByText('printer').tagName).toBe('MARK');
    const [asked] = fake.find('GET', '/api/v1/knowledge/suggestions');
    expect(asked?.url.searchParams.get('text')).toBe('printer jammed');

    fireEvent.click(screen.getByTestId(`kb-suggestion-link-${ARTICLE_ID}`));
    expect(
      screen.getByTestId(`kb-suggestion-link-${ARTICLE_ID}`).getAttribute('aria-pressed'),
    ).toBe('true');
    fireEvent.mouseDown(selectorOf(screen.getByTestId('inc-requester')));
    fireEvent.click(await screen.findByText('rana@demo.test'));
    fireEvent.click(screen.getByTestId('inc-save'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/knowledge/articles/${ARTICLE_ID}/links`)).toHaveLength(1);
    });
    expect(fake.find('POST', `/api/v1/knowledge/articles/${ARTICLE_ID}/links`)[0]?.body).toEqual({
      record_type: 'incident',
      record_id: ITEM.id,
      how: 'suggestion',
    });
  });

  it('AC3: switched off in Admin › Knowledge, the form has no suggestions', async () => {
    const fake = open(false);
    render(<App />);
    expect(await screen.findByTestId('inc-subject')).toBeDefined();
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/knowledge/settings')).toHaveLength(1);
    });
    expect(screen.queryByTestId('kb-suggestions')).toBeNull();
  });
});
