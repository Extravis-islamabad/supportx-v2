import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { rememberTab } from './tabs';

// WP-025 session 2: the SLA panel (REQ-SLA-038) and due dates set by hand (REQ-SLA-028).

const SESSION_USER = '01900000-0000-7000-8000-000000000101';
const POLICY = '01900000-0000-7000-8000-00000000c001';
const ITEM = {
  ...fakeIncident(),
  sla_policy_id: POLICY,
  resolution_due_at: '2026-11-03T12:00:00Z',
};
const PATH = `/api/v1/incidents/${ITEM.id}`;

function target(kind: 'first_response' | 'resolution', extra: Record<string, unknown> = {}) {
  return {
    kind,
    round: 1,
    state: 'running',
    target_seconds: 3600,
    used_seconds: 0,
    paused_seconds: 0,
    running_since: '2026-11-02T08:00:00Z',
    paused_since: null,
    due_at: '2026-11-03T12:00:00Z',
    warning_at: null,
    met_at: null,
    met_how: null,
    breached_at: null,
    breach_seconds: null,
    calendar_id: null,
    calendar_name: 'Office hours',
    manual: null,
    ...extra,
  };
}

function panel(extra: Record<string, unknown> = {}) {
  return {
    policy_id: POLICY,
    policy_name: 'Standard support',
    reason: 'created',
    applied_at: '2026-11-02T08:00:00Z',
    may_set_due_dates: false,
    targets: [
      target('first_response', { state: 'met', met_how: 'at_resolution', due_at: null }),
      target('resolution'),
    ],
    ...extra,
  };
}

let restore: () => void = () => undefined;
function api(routes: Record<string, unknown>) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
      ...routes,
    } as Parameters<typeof consoleApi>[0] extends { routes?: infer R } | undefined ? R : never,
  });
  restore = fake.restore;
  return fake;
}

describe('SLA panel (WP-025)', () => {
  afterEach(() => {
    restore();
  });

  it('REQ-SLA-038: policy, why, each target with its state and calendar, in words', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'details');
    api({ [`GET ${PATH}/sla`]: { body: panel() } });
    render(<App />);
    const card = await screen.findByTestId('inc-sla');
    expect(within(card).getByTestId('inc-sla-policy').textContent).toBe('Standard support');
    expect(card.textContent).toContain('When the incident was created');
    // D-115 D8: "met at resolution" is its own state.
    expect(screen.getByTestId('inc-sla-first_response-state').textContent).toBe(
      'Met at resolution',
    );
    expect(screen.getByTestId('inc-sla-resolution-state').textContent).toBe('Running');
    expect(card.textContent).toContain('Office hours');
    // No raw codes reach the screen (rule d).
    expect(card.textContent).not.toMatch(/at_resolution|first_response|running/);
    // Without the permission there is nothing to change.
    expect(screen.queryByTestId('inc-sla-resolution-change')).toBeNull();
  });

  it('REQ-SLA-028: a date set by hand shows who and why; changing it needs a reason', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'details');
    const manual = {
      due_at: '2026-11-05T09:00:00Z',
      by_id: SESSION_USER,
      by_name: 'Sara Admin',
      reason: 'Agreed with the requester',
      at: '2026-11-02T09:00:00Z',
    };
    const fake = api({
      [`GET ${PATH}/sla`]: {
        body: panel({
          may_set_due_dates: true,
          targets: [target('resolution', { manual, due_at: manual.due_at })],
        }),
      },
      [`PUT ${PATH}/due-dates/resolution`]: { body: { ...ITEM, version: 2 } },
    });
    render(<App />);
    const marker = await screen.findByTestId('inc-sla-resolution-manual');
    expect(marker.textContent).toContain('Set by hand by Sara Admin: Agreed with the requester');
    // AC1: the panel says why the date does not move.
    expect(marker.textContent).toContain('stays when the priority or policy changes');
    fireEvent.click(screen.getByTestId('inc-sla-resolution-change'));
    const clear = await screen.findByTestId('inc-sla-due-clear');
    expect((clear as HTMLButtonElement).disabled).toBe(true); // a reason first
    fireEvent.change(screen.getByTestId('inc-sla-due-reason'), {
      target: { value: 'Back to normal' },
    });
    fireEvent.click(screen.getByTestId('inc-sla-due-clear'));
    await waitFor(() => {
      expect(fake.find('PUT', `${PATH}/due-dates/resolution`)).toHaveLength(1);
    });
    const sent = fake.find('PUT', `${PATH}/due-dates/resolution`)[0];
    expect(sent?.body).toEqual({ due_at: null, reason: 'Back to normal' });
    expect(sent?.headers.get('If-Match')).toBe('"1"');
  });

  it('REQ-INC-011: no policy says so', async () => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'details');
    api({ [`GET ${PATH}/sla`]: { body: panel({ policy_id: null, targets: [] }) } });
    render(<App />);
    expect((await screen.findByTestId('inc-sla-none')).textContent).toBe('No SLA applies');
  });
});
