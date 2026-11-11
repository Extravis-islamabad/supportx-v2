import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-058b S1 (REQ-REL-038): the release calendar on the shared staged calendar. Releases by
// their deployment window, the timeline view, the quick view, and a move by keyboard that writes
// the deployment stage without the change-only re-approval preview.

const REL_ID = '01a1a2b3-0000-7000-8000-00000058b001';

const entry = {
  record_id: REL_ID,
  display_id: 'REL-7',
  subject: 'Payroll 4.2',
  stage: 'deployment',
  status: 'deployment_scheduled',
  stage_path: 'default',
  group_id: null,
  site_id: null,
  technician_id: null,
  kind: 'window',
  starts_at: '2027-03-10T09:00:00Z',
  ends_at: '2027-03-11T11:00:00Z',
  part_id: null,
  version: 2,
};

let restore: () => void = () => undefined;
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2027-03-10T08:00:00Z'));
});
afterEach(() => {
  vi.useRealTimers();
  restore();
});

const CHG_IN = '01a1a2b3-0000-7000-8000-00000058b011';
const CHG_OUT = '01a1a2b3-0000-7000-8000-00000058b012';
const change = (id: string, display: string, day: string) => ({
  ...entry,
  record_id: id,
  display_id: display,
  subject: `${display} work`,
  stage: 'implementation',
  status: 'implementation_scheduled',
  starts_at: `2027-${day}T13:00:00Z`,
  ends_at: `2027-${day}T14:00:00Z`,
  version: 5,
});

function api(permissions: string[] = ['releases.view', 'releases.edit']) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['technician'] },
      {
        permissions: permissions.map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      'GET /api/v1/release-calendar': { body: [entry] },
      'GET /api/v1/change-windows': { body: [] },
      'GET /api/v1/change-calendar': {
        body: [change(CHG_IN, 'CHG-31', '03-10'), change(CHG_OUT, 'CHG-32', '03-10')],
      },
      [`GET /api/v1/releases/${REL_ID}/schedule`]: {
        body: [
          {
            stage: 'deployment',
            scheduled_start: '2027-03-10T09:00:00Z',
            scheduled_end: '2027-03-11T11:00:00Z',
            actual_start: null,
            actual_end: null,
            outcome: null,
            version: 2,
            overdue: false,
          },
        ],
      },
      [`GET /api/v1/releases/${REL_ID}/changes`]: {
        body: [
          {
            id: CHG_IN,
            visible: true,
            display_id: 'CHG-31',
            subject: 'CHG-31 work',
            stage: 'implementation',
            status: 'implementation_scheduled',
            status_category: 'open',
          },
        ],
      },
      [`PATCH /api/v1/releases/${REL_ID}/schedule/deployment`]: {
        body: {
          stage: 'deployment',
          scheduled_start: '2027-03-12T09:00:00Z',
          scheduled_end: '2027-03-13T11:00:00Z',
          version: 3,
        },
      },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: the release calendar (WP-058b S1)', () => {
  it('REQ-REL-038: a release on its deployment days, opened in a quick view', async () => {
    window.history.pushState({}, '', '/releases/calendar');
    api();
    render(<App />);
    expect((await screen.findByTestId('calendar-header')).textContent).toContain(
      'Release calendar',
    );
    const day = await screen.findByTestId('calendar-day-2027-03-11');
    fireEvent.click(within(day).getByTestId('calendar-open-REL-7-window'));
    const quick = await screen.findByTestId('calendar-quick');
    expect(quick.textContent).toContain('Payroll 4.2');
    expect(within(quick).getByTestId('calendar-quick-open').getAttribute('href')).toBe(
      `/releases/${REL_ID}`,
    );
  });

  it('the timeline: one row per release, its bar across its two days', async () => {
    window.history.pushState({}, '', '/releases/calendar');
    api();
    render(<App />);
    await screen.findByTestId('calendar-day-2027-03-10');
    fireEvent.click(screen.getByText('Timeline'));
    const timeline = await screen.findByTestId('calendar-timeline');
    const bar = within(timeline).getByTestId('timeline-REL-7-window');
    // Column 1 is the label: the 10th is column 11, the bar ends after the 11th.
    expect(bar.style.gridColumn).toBe('11 / 13');
    expect(within(timeline).getAllByRole('columnheader')).toHaveLength(31);
  });

  it('a move by keyboard writes the deployment stage, with no change re-approval', async () => {
    window.history.pushState({}, '', '/releases/calendar');
    const fake = api();
    render(<App />);
    // Across two days, so on both: either one moves it.
    const [first] = await screen.findAllByTestId('calendar-move-REL-7');
    if (first === undefined) throw new Error('no move button');
    fireEvent.click(first);
    const input = await screen.findByTestId('calendar-move-day');
    fireEvent.mouseDown(input);
    fireEvent.change(input, { target: { value: '12 Mar 2027' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    fireEvent.click(screen.getByTestId('calendar-move-ok'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/releases/${REL_ID}/schedule/deployment`)).toHaveLength(1);
    });
    const [moved] = fake.find('PATCH', `/api/v1/releases/${REL_ID}/schedule/deployment`);
    expect(moved?.headers.get('If-Match')).toBe('"2"');
    expect(moved?.body).toEqual({
      scheduled_start: '2027-03-12T09:00:00.000Z',
      scheduled_end: '2027-03-13T11:00:00.000Z',
    });
    expect(
      fake.find('POST', `/api/v1/changes/${REL_ID}/approvals/reapproval-preview`),
    ).toHaveLength(0);
  });

  it('REQ-REL-038 AC1: "Show changes" draws changes beside releases, with a legend', async () => {
    window.history.pushState({}, '', '/releases/calendar');
    const fake = api(['releases.view', 'releases.edit', 'changes.view']);
    render(<App />);
    const day = await screen.findByTestId('calendar-day-2027-03-10');
    expect(within(day).queryByTestId('calendar-entry-CHG-31-window')).toBeNull();
    expect(fake.find('GET', '/api/v1/change-calendar')).toHaveLength(0); // not asked until shown
    fireEvent.click(screen.getByTestId('calendar-show-other'));
    const chip = await within(day).findByTestId('calendar-entry-CHG-32-window');
    expect(chip.getAttribute('data-type')).toBe('changes');
    expect(within(day).getByTestId('calendar-entry-REL-7-window').getAttribute('data-type')).toBe(
      'releases',
    );
    const legend = screen.getByTestId('calendar-legend');
    expect(legend.textContent).toContain('Releases');
    expect(legend.textContent).toContain('Changes');
    // A change opens as a change.
    fireEvent.click(within(day).getByTestId('calendar-open-CHG-32-window'));
    expect((await screen.findByTestId('calendar-quick-open')).getAttribute('href')).toBe(
      `/changes/${CHG_OUT}`,
    );
  });

  it('without changes.view there is no "Show changes"', async () => {
    window.history.pushState({}, '', '/releases/calendar');
    api();
    render(<App />);
    await screen.findByTestId('calendar-day-2027-03-10');
    expect(screen.queryByTestId('calendar-show-other')).toBeNull();
  });

  it("REQ-REL-039 AC1: the release's scheduler opens on its deployment with only its changes", async () => {
    vi.setSystemTime(new Date('2027-01-05T08:00:00Z')); // today is two months earlier
    window.history.pushState({}, '', `/releases/calendar?focus=${REL_ID}`);
    api(['releases.view', 'releases.edit', 'changes.view']);
    render(<App />);
    const day = await screen.findByTestId('calendar-day-2027-03-10'); // centred on March
    await within(day).findByTestId('calendar-entry-CHG-31-window');
    expect(within(day).queryByTestId('calendar-entry-CHG-32-window')).toBeNull();
    expect(within(day).getByTestId('calendar-entry-REL-7-window').style.outline).toContain('solid');
    fireEvent.click(screen.getByTestId('calendar-only-linked'));
    await within(day).findByTestId('calendar-entry-CHG-32-window');
  });
});
