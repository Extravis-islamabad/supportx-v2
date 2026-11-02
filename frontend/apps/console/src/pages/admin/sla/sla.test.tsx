import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { SlaCalendar, SlaHoliday, SlaHolidayList } from '@supportx/api-client';

import { App } from '../../../App';
import { consoleApi, fakeSession, problem } from '../../../test/api';
import { weekMinutes } from './week';

// WP-025 session 1 screens: Admin › SLA (working calendars, holidays).
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const TECH = fakeSession({ display_name: 'Tariq Tech', roles: ['technician'] });
const CALENDARS = '/api/v1/sla/calendars';
const LISTS = '/api/v1/sla/holiday-lists';
const MON_FRI = [0, 1, 2, 3, 4].map((weekday) => ({ weekday, start: '09:00', end: '18:00' }));

function calendar(overrides: Partial<SlaCalendar> = {}): SlaCalendar {
  return {
    id: 'cal-hours',
    name: 'Operating hours',
    labels: {},
    time_zone: 'Asia/Karachi',
    kind: 'hours',
    system_key: 'operating_hours',
    week: MON_FRI,
    holiday_list_ids: [],
    used_by_sites: [],
    used_by_groups: [],
    fixed: false,
    can_manage: true,
    delete_refusal: 'system_calendar',
    version: 1,
    ...overrides,
  };
}

const AROUND = calendar({
  id: 'cal-24',
  name: 'Around the clock',
  kind: 'around_the_clock',
  system_key: 'around_the_clock',
  time_zone: 'UTC',
  week: [],
  fixed: true,
});
const RIYADH = calendar({
  id: 'cal-riyadh',
  name: 'Riyadh office',
  system_key: null,
  time_zone: 'Asia/Riyadh',
  week: [6, 0, 1, 2, 3].map((weekday) => ({ weekday, start: '08:00', end: '17:00' })),
  used_by_sites: [{ id: 's1', name: 'Riyadh HQ' }],
  used_by_groups: [{ id: 'g1', name: 'Service Desk' }],
  delete_refusal: 'calendar_in_use',
  holiday_list_ids: ['list-1'],
});

const LIST: SlaHolidayList = {
  id: 'list-1',
  name: 'Saudi Arabia',
  labels: {},
  holiday_count: 1,
  calendar_ids: ['cal-riyadh'],
  can_manage: true,
  version: 1,
};

function holiday(overrides: Partial<SlaHoliday> = {}): SlaHoliday {
  return {
    id: 'h-1',
    list_id: 'list-1',
    name: 'Founding Day',
    starts_on: `${String(new Date().getFullYear())}-02-22`,
    ends_on: `${String(new Date().getFullYear())}-02-22`,
    part: 'full',
    needs_review: false,
    origin: 'manual',
    version: 1,
    ...overrides,
  };
}

const ROUTES = {
  [`GET ${CALENDARS}`]: { body: [AROUND, calendar(), RIYADH] },
  [`GET ${LISTS}`]: { body: [LIST] },
};

describe('Admin › SLA › Working calendars', () => {
  afterEach(() => {
    restore();
  });

  it('lists the system calendars by label, hours a week, and who uses each one', async () => {
    window.history.pushState({}, '', '/admin/sla');
    api({ me: ADMIN, routes: ROUTES });
    render(<App />);
    const table = await screen.findByTestId('sla-calendars');
    const around = await within(table).findByTestId('sla-calendar-row-cal-24');
    expect(around.textContent).toContain('Around the clock');
    const hours = within(table).getByTestId('sla-calendar-row-cal-hours');
    expect(hours.textContent).toContain('45 working hours a week');
    expect(hours.textContent).toContain('Asia/Karachi');
    const riyadh = within(table).getByTestId('sla-calendar-row-cal-riyadh');
    expect(riyadh.textContent).toContain('Saudi Arabia');
    expect(within(riyadh).getByTestId('sla-calendar-used-cal-riyadh').textContent).toBe(
      'Riyadh HQ · Service Desk',
    );
    // No raw codes anywhere on the screen.
    expect(document.body.textContent).not.toMatch(/operating_hours|around_the_clock|in_use/);
  });

  it('says why a calendar cannot be deleted instead of offering it', async () => {
    window.history.pushState({}, '', '/admin/sla/calendars');
    api({ me: ADMIN, routes: ROUTES });
    render(<App />);
    const remove = await screen.findByTestId('sla-calendar-delete-cal-riyadh');
    expect(remove.hasAttribute('disabled')).toBe(true);
    // Its tooltip comes from the action reason, a label.
    const reason = screen.getByTestId('sla-calendar-delete-reason-cal-riyadh');
    fireEvent.mouseEnter(reason.firstElementChild ?? reason);
    const tip = await screen.findByRole('tooltip');
    expect(tip.textContent).toBe('Sites or support groups use this calendar.');
  });

  it('adds a calendar from a preset with one idempotency key, and shows field problems', async () => {
    window.history.pushState({}, '', '/admin/sla/calendars');
    const fake = api({
      me: ADMIN,
      routes: {
        ...ROUTES,
        [`POST ${CALENDARS}`]: {
          status: 422,
          body: problem(422, 'validation_failed', {
            errors: [
              {
                field: 'body.name',
                code: 'name_taken',
                message_key: 'errors.field.name_taken',
                params: {},
              },
            ],
          }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sla-calendar-add'));
    const editor = await screen.findByTestId('sla-calendar-editor');
    fireEvent.change(within(editor).getByTestId('sla-calendar-name'), {
      target: { value: 'Riyadh office' },
    });
    fireEvent.click(within(editor).getByTestId('sla-calendar-save'));
    expect(await within(editor).findByText('Another one already uses this name.')).toBeTruthy();
    fireEvent.click(within(editor).getByTestId('sla-calendar-save'));
    await waitFor(() => {
      expect(fake.find('POST', CALENDARS)).toHaveLength(2);
    });
    const [first, second] = fake.find('POST', CALENDARS);
    expect(first?.body).toMatchObject({ name: 'Riyadh office', preset: 'mon_fri' });
    // A retried save reuses the form's key, so it can never make a second calendar.
    expect(first?.headers.get('idempotency-key')).toBe(second?.headers.get('idempotency-key'));
  });

  it('edits the working week: a night period is marked as ending the next day', async () => {
    window.history.pushState({}, '', '/admin/sla/calendars');
    const fake = api({
      me: ADMIN,
      routes: { ...ROUTES, [`PATCH ${CALENDARS}/cal-riyadh`]: { body: RIYADH } },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sla-calendar-row-cal-riyadh'));
    const editor = await screen.findByTestId('sla-calendar-editor');
    expect(within(editor).getByTestId('sla-calendar-used-by').textContent).toContain('Riyadh HQ');
    fireEvent.click(within(editor).getByTestId('sla-week-add'));
    const added = within(editor).getByTestId('sla-week-row-5');
    expect(added.textContent).toContain('Friday');
    const end = within(added).getByRole('combobox', { name: 'To' });
    fireEvent.mouseDown(end);
    fireEvent.click(await screen.findByTitle('02:00'));
    expect(await within(added).findByText('Ends the next day')).toBeTruthy();
    fireEvent.click(within(editor).getByTestId('sla-calendar-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `${CALENDARS}/cal-riyadh`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `${CALENDARS}/cal-riyadh`);
    expect(sent?.headers.get('if-match')).toBe('"1"');
    expect((sent?.body as { week: unknown[] }).week).toHaveLength(6);
  });

  it('around the clock only takes a new name', async () => {
    window.history.pushState({}, '', '/admin/sla/calendars');
    api({ me: ADMIN, routes: ROUTES });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sla-calendar-row-cal-24'));
    const editor = await screen.findByTestId('sla-calendar-editor');
    expect(
      within(editor).getByText(
        'Around the clock counts every hour of every day. Only its name can change.',
      ),
    ).toBeTruthy();
    expect(within(editor).queryByTestId('sla-week')).toBeNull();
    expect(within(editor).queryByTestId('sla-calendar-zone')).toBeNull();
  });

  it('technicians read the calendars but cannot change them', async () => {
    window.history.pushState({}, '', '/admin/sla/calendars');
    api({ me: TECH, routes: ROUTES });
    render(<App />);
    await screen.findByTestId('sla-calendar-row-cal-riyadh');
    expect(screen.queryByTestId('sla-calendar-add')).toBeNull();
    expect(screen.queryByTestId('sla-calendar-delete-cal-riyadh')).toBeNull();
  });

  it('counts a night period once, across midnight', () => {
    expect(weekMinutes([{ weekday: 0, start: '22:00', end: '06:00' }])).toBe(8 * 60);
    expect(weekMinutes([{ weekday: 0, start: '16:00', end: '24:00' }])).toBe(8 * 60);
    expect(weekMinutes(MON_FRI)).toBe(45 * 60);
  });
});

describe('Admin › SLA › Holidays', () => {
  afterEach(() => {
    restore();
  });

  const year = new Date().getFullYear();
  // The fake API matches the path; the year goes in the query string.
  const holidays = `${LISTS}/list-1/holidays`;

  it('shows a list’s holidays with their part and a review flag', async () => {
    window.history.pushState({}, '', '/admin/sla/holidays');
    api({
      me: ADMIN,
      routes: {
        ...ROUTES,
        [`GET ${holidays}`]: {
          body: [
            holiday(),
            holiday({
              id: 'h-2',
              name: 'Eid',
              part: 'afternoon',
              needs_review: true,
              origin: 'copy',
            }),
          ],
        },
      },
    });
    render(<App />);
    const table = await screen.findByTestId('sla-holiday-table');
    const eid = await within(table).findByTestId('sla-holiday-row-h-2');
    expect(eid.textContent).toContain('Afternoon off');
    expect(eid.textContent).toContain('Check this date');
    expect(eid.textContent).toContain('Copied from last year');
    expect(screen.getByTestId('sla-holiday-list-list-1').textContent).toContain('1 holiday');
  });

  it('imports an iCalendar file and lists what it skipped, in words', async () => {
    window.history.pushState({}, '', '/admin/sla/holidays');
    const fake = api({
      me: ADMIN,
      routes: {
        ...ROUTES,
        [`GET ${holidays}`]: { body: [] },
        [`POST ${LISTS}/list-1/import`]: {
          status: 201,
          body: {
            created: [holiday()],
            skipped: [
              { name: 'Weekly meeting', reason: 'repeating' },
              { name: 'Founding Day', reason: 'duplicate' },
            ],
          },
        },
      },
    });
    render(<App />);
    await screen.findByTestId('sla-holiday-table');
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (input === null) throw new Error('no file input');
    // The fake API reads request bodies as JSON, so the stand-in file holds a JSON string.
    const file = new File(['"BEGIN:VCALENDAR"'], 'holidays.ics', { type: 'text/calendar' });
    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
      await Promise.resolve();
    });
    const skipped = await screen.findByTestId('sla-import-skipped');
    expect(skipped.textContent).toContain(
      "Weekly meeting: Repeats by a rule: add each year's date instead",
    );
    expect(skipped.textContent).toContain('Founding Day: Already in the list');
    expect(fake.find('POST', `${LISTS}/list-1/import`)).toHaveLength(1);
  });

  it('copies a year with the next year named on the button', async () => {
    window.history.pushState({}, '', '/admin/sla/holidays');
    const fake = api({
      me: ADMIN,
      routes: {
        ...ROUTES,
        [`GET ${holidays}`]: { body: [holiday()] },
        [`POST ${LISTS}/list-1/copy-year`]: {
          status: 201,
          body: { created: [holiday({ needs_review: true })], skipped: [] },
        },
      },
    });
    render(<App />);
    const copy = await screen.findByTestId('sla-holidays-copy');
    expect(copy.textContent).toBe(`Copy ${String(year)} to ${String(year + 1)}`);
    fireEvent.click(copy);
    await waitFor(() => {
      expect(fake.find('POST', `${LISTS}/list-1/copy-year`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${LISTS}/list-1/copy-year`)[0]?.body).toEqual({ year });
  });

  it('a half day over several days is refused under the field that says so', async () => {
    window.history.pushState({}, '', '/admin/sla/holidays');
    api({
      me: ADMIN,
      routes: {
        ...ROUTES,
        [`GET ${holidays}`]: { body: [] },
        [`POST ${LISTS}/list-1/holidays`]: {
          status: 422,
          body: problem(422, 'validation_failed', {
            errors: [
              {
                field: 'body.part',
                code: 'half_day_single_date',
                message_key: 'errors.field.half_day_single_date',
                params: {},
              },
            ],
          }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('sla-holiday-add'));
    const editor = await screen.findByTestId('sla-holiday-editor');
    fireEvent.change(within(editor).getByTestId('sla-holiday-name'), {
      target: { value: 'Long weekend' },
    });
    fireEvent.click(within(editor).getByTestId('sla-holiday-save'));
    expect(
      await within(editor).findByText('A morning or afternoon off is one day only.'),
    ).toBeTruthy();
  });
});
