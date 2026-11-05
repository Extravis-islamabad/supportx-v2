import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-044a s5: problems in the console: the list, creating one from an incident (prefilled, with
// similar problems), and the record with the guided steps and investigators.

const PRB_ID = '01a1a2b3-0000-7000-8000-00000000e001';
const INC_ID = '01a1a2b3-0000-7000-8000-00000000c101';
const TEMPLATE_ID = '01a1a2b3-0000-7000-8000-00000000f001';
const TECH = '01a1a2b3-0000-7000-8000-00000000b101';

const record = fakeIncident({
  id: PRB_ID,
  type: 'problem',
  display_id: 'PRB-7',
  subject: 'Mail relay drops messages',
  status: 'gathering_facts',
  lifecycle: 'guided_analysis',
  actions: [
    {
      action: 'analyse',
      allowed: true,
      reason: null,
      reason_mode: 'none',
      reason_list: null,
    },
  ],
});

const template = {
  id: TEMPLATE_ID,
  code: 'standard',
  labels: null,
  description: null,
  group_name: null,
  is_default: true,
  for_requesters: false,
  disabled: false,
  copied_from_id: null,
  fields: {},
  custom_fields: {},
  defaults: {},
  lifecycle: 'standard',
  version: 1,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(routes: Record<string, unknown> = {}) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/problems': {
        body: { items: [record], next_cursor: null, has_more: false, people: {} },
      },
      'GET /api/v1/problems/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/problems/templates': { body: [template] },
      'GET /api/v1/problems/similar': { body: [] },
      [`GET /api/v1/problems/${PRB_ID}`]: { body: record },
      [`GET /api/v1/problems/${PRB_ID}/links`]: { body: [] },
      [`GET /api/v1/problems/${PRB_ID}/investigators`]: {
        body: {
          user_ids: [TECH],
          people: { [TECH]: { display_name: 'Nadia Network', email: 'nadia@example.com' } },
        },
      },
      ...routes,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: problems', () => {
  it('lists problems with a way to create one', async () => {
    window.history.pushState({}, '', '/problems');
    api();
    render(<App />);
    const row = (await screen.findByTestId('prb-row-PRB-7')).closest('tr');
    expect(within(row as HTMLElement).getByText('Mail relay drops messages')).toBeDefined();
    expect(screen.getByTestId('prb-new')).toBeDefined();
  });

  it('creates one from an incident: prefilled, similar problems shown, linked on save', async () => {
    window.history.pushState({}, '', `/problems/new?incident=${INC_ID}`);
    const fake = api({
      'GET /api/v1/problems/prefill': {
        body: {
          subject: 'Mail is down',
          description: null,
          impact: null,
          urgency: null,
          site_id: null,
          category_id: null,
          requester_id: TECH,
          problem_type: 'reactive',
          source_incident_id: INC_ID,
        },
      },
      'GET /api/v1/problems/similar': {
        body: [
          {
            id: PRB_ID,
            display_id: 'PRB-7',
            subject: 'Mail relay drops messages',
            status: 'investigating',
            status_category: 'open',
          },
        ],
      },
      'POST /api/v1/problems/from-incidents': {
        status: 201,
        body: { problem: record, bulk_jobs: [] },
      },
    });
    render(<App />);
    const subject = await screen.findByTestId('prb-subject');
    expect((subject as HTMLInputElement).value).toBe('Mail is down');
    expect(await screen.findByTestId('prb-similar-PRB-7')).toBeDefined();
    fireEvent.click(screen.getByTestId('prb-create'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/problems/from-incidents')).toHaveLength(1);
    });
    const sent = fake.find('POST', '/api/v1/problems/from-incidents')[0]?.body as {
      main_incident_id: string;
      problem: { subject: string; requester_id: string; template_id: string };
    };
    expect(sent.main_incident_id).toBe(INC_ID);
    expect(sent.problem.subject).toBe('Mail is down');
    expect(sent.problem.requester_id).toBe(TECH); // reported by: the creator
    expect(sent.problem.template_id).toBe(TEMPLATE_ID); // the default template first
    await screen.findByTestId('prb-record');
  });

  it('shows the guided steps, the next move and the investigators', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    api();
    render(<App />);
    const steps = await screen.findByTestId('prb-guided-steps');
    expect(within(steps).getByText('Gathering facts')).toBeDefined();
    expect(within(steps).getByText('In review')).toBeDefined();
    expect(await screen.findByRole('button', { name: 'Start the why-analysis' })).toBeDefined();
    expect(await screen.findByText('Nadia Network')).toBeDefined();
  });
});
