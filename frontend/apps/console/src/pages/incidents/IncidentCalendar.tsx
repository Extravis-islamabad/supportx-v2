// Its staged counterpart is pages/staged/ScheduleCalendar.tsx (same look, calendarMath only; one
// shared grid for both is on the polish list, lane C 2026-11-20).
import { useIncidents, type FilterExpression, type IncidentListItem } from '@supportx/api-client';
import { useAppearance, useLabel, useMinWidth, useTimeZone } from '@supportx/ui';
import { Alert, Button, Flex, Popover, Segmented, Typography, theme } from 'antd';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router';

import {
  addDays,
  dayKey,
  dayOf,
  daysOf,
  normal,
  rangeOf,
  step,
  weekStart,
  type CalendarView,
  type Day,
} from '../staged/calendarMath';

const WEEK_START = { sunday: 0, monday: 1, saturday: 6 } as const;
/** Chips a month cell shows before "N more" (incidents stack up on a due day; lane C). */
export const CELL_CHIPS = 4;
/** The most records one view asks for; past it a line says the calendar is partial. */
const MOST = 1000;
const DUE = 'resolution_due_at';

type Shown = Extract<CalendarView, 'month' | 'week'>;

const both = (a: FilterExpression | undefined, ...more: FilterExpression[]): FilterExpression => ({
  and: a === undefined ? more : [a, ...more],
});

/**
 * The incident list as a calendar (REQ-INC-112; WP-046b S3b): the current view's records by their
 * resolution due time, in month or week, days being wall-clock days in your zone (AC1). It asks
 * the list with the view's own filter plus the visible range (AC2), by the POST form, so a
 * sealed filter works and stays out of the URL. Records with no due time are left out and
 * counted. Read-only: a due time is the SLA's, changed on the record.
 *
 * Keyboard (lane C): one day is in the Tab order; the arrows move between days in the direction
 * they point on screen (mirrored right to left), Home/End go to the week's first and last day,
 * PageUp/PageDown move a month, Enter opens the day's list. Escape closes only that list.
 */
export function IncidentCalendar({
  view,
  tag,
  filter,
}: {
  view?: string;
  tag?: string;
  filter?: FilterExpression;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const { locale, dates, direction } = useAppearance();
  const { token } = theme.useToken();
  const zone = useTimeZone();
  const wide = useMinWidth(768);
  const firstDay = WEEK_START[dates.weekStart];
  const [shown, setShown] = useState<Shown>('month');
  const [anchor, setAnchor] = useState<Day>(() => dayOf(new Date().toISOString(), zone));
  const [focused, setFocused] = useState<string>(() => dayKey(anchor));
  const [open, setOpen] = useState<string | null>(null);
  const cells = useRef(new Map<string, HTMLDivElement>());
  const days = useMemo(() => daysOf(shown, anchor, firstDay), [shown, anchor, firstDay]);
  const range = useMemo(() => rangeOf(days, zone), [days, zone]);

  const inRange = useIncidents({
    view,
    tag,
    filter: both(
      filter,
      { field: DUE, op: 'gte', value: range.start },
      { field: DUE, op: 'lt', value: range.end },
    ),
    sort: DUE,
    limit: 200,
  });
  const undated = useIncidents({
    view,
    tag,
    filter: both(filter, { field: DUE, op: 'is_null' } as FilterExpression),
    limit: 1,
  });
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = inRange;
  const rows: IncidentListItem[] = useMemo(
    () => (inRange.data?.pages ?? []).flatMap((p) => p.items),
    [inRange.data],
  );
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && rows.length < MOST) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, rows.length, fetchNextPage]);
  const noDue = undated.data?.pages[0]?.estimated_total ?? 0;

  const today = dayKey(dayOf(new Date().toISOString(), zone));
  const fmt = (d: Day, options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat(locale, { ...options, timeZone: 'UTC' }).format(
      new Date(Date.UTC(d.year, d.month, d.day)),
    );
  // A due time is an instant: it sits on its own wall-clock day in your zone.
  const byDay = useMemo(() => {
    const found = new Map<string, IncidentListItem[]>();
    for (const r of rows) {
      if (r.resolution_due_at == null) continue;
      const key = dayKey(dayOf(r.resolution_due_at, zone));
      found.set(key, [...(found.get(key) ?? []), r]);
    }
    return found;
  }, [rows, zone]);
  const onDay = (d: Day) => byDay.get(dayKey(d)) ?? [];
  const mores = useRef(new Map<string, HTMLElement>());
  const close = (key: string) => {
    setOpen(null);
    requestAnimationFrame(() => mores.current.get(key)?.focus());
  };

  const goTo = (d: Day) => {
    const next = normal(d);
    const key = dayKey(next);
    if (!days.some((x) => dayKey(x) === key)) setAnchor(next);
    setFocused(key);
    setOpen(null);
    requestAnimationFrame(() => cells.current.get(key)?.focus());
  };
  const current = days.find((d) => dayKey(d) === focused) ?? days[0] ?? anchor;
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const ahead = direction === 'rtl' ? -1 : 1;
    const moves: Record<string, () => Day> = {
      ArrowRight: () => addDays(current, ahead),
      ArrowLeft: () => addDays(current, -ahead),
      ArrowDown: () => addDays(current, 7),
      ArrowUp: () => addDays(current, -7),
      Home: () => weekStart(current, firstDay),
      End: () => addDays(weekStart(current, firstDay), 6),
      PageDown: () => ({ ...current, month: current.month + 1 }),
      PageUp: () => ({ ...current, month: current.month - 1 }),
    };
    const move = moves[event.key];
    if (move !== undefined) {
      event.preventDefault();
      goTo(move());
    } else if (event.key === 'Enter' && event.target === cells.current.get(focused)) {
      // Enter opens the day: its full list when it has more than it shows, else its first record.
      event.preventDefault();
      if (mores.current.has(focused)) setOpen(focused);
      else cells.current.get(focused)?.querySelector<HTMLElement>('button')?.focus();
    }
  };

  const chip = (r: IncidentListItem) => (
    <Button
      key={r.id}
      type="link"
      size="small"
      onClick={() => void navigate(`/incidents/${r.id}`)}
      data-testid={`inc-cal-entry-${r.display_id}`}
      title={`${r.display_id} ${r.subject}`}
      style={{
        // The staged calendar's chip (ScheduleCalendar's entryChip), so the two read alike.
        display: 'block',
        textAlign: 'start',
        color: 'inherit',
        height: 'auto',
        borderInlineStart: `3px solid ${token.colorPrimary}`,
        borderRadius: token.borderRadiusSM,
        background: token.colorFillTertiary,
        paddingInline: 6,
        paddingBlock: 2,
        marginBottom: 2,
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        maxWidth: '100%',
      }}
    >
      <bdi dir="ltr" style={{ fontWeight: 600 }}>
        {r.display_id}
      </bdi>{' '}
      {r.subject}
    </Button>
  );

  const dayList = (d: Day, list: IncidentListItem[]) => (
    <ul
      onKeyDown={(event) => {
        // Escape closes only this list, and focus goes back to its "N more" (lane C).
        if (event.key === 'Escape') {
          event.stopPropagation();
          close(dayKey(d));
        }
      }}
      aria-label={t('incidents.calendar.day_list', { day: fmt(d, { dateStyle: 'full' }) })}
      style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 320, overflowY: 'auto' }}
      data-testid={`inc-cal-list-${dayKey(d)}`}
    >
      {list.map((r) => (
        <li key={r.id}>{chip(r)}</li>
      ))}
    </ul>
  );

  const cell = (d: Day) => {
    const key = dayKey(d);
    const list = onDay(d);
    const outside = shown === 'month' && d.month !== normal(anchor).month;
    const fullDate = fmt(d, { dateStyle: 'full' });
    const cap = shown === 'month' ? (wide ? CELL_CHIPS : 0) : Number.POSITIVE_INFINITY;
    const extra = list.length - Math.min(list.length, cap);
    return (
      <div
        key={key}
        ref={(node) => {
          if (node === null) cells.current.delete(key);
          else cells.current.set(key, node);
        }}
        role="gridcell"
        aria-label={fullDate}
        aria-selected={key === focused}
        tabIndex={key === focused ? 0 : -1}
        onFocus={() => {
          setFocused(key);
        }}
        data-testid={`inc-cal-day-${key}`}
        style={{
          minHeight: shown === 'week' ? 96 : wide ? 110 : 72,
          padding: wide ? 6 : 2,
          border: `1px solid ${token.colorBorderSecondary}`,
          // As the staged calendar: out of the month is a quieter background and secondary
          // text, never opacity, so chips keep their contrast.
          background:
            key === today
              ? token.colorPrimaryBg
              : outside
                ? token.colorFillQuaternary
                : token.colorBgContainer,
          minWidth: 0,
          outline: key === focused ? `2px solid ${token.colorPrimary}` : undefined,
          outlineOffset: -2,
        }}
      >
        <Typography.Text strong={key === today} type={outside ? 'secondary' : undefined}>
          {shown === 'month'
            ? fmt(d, { day: 'numeric' })
            : fmt(d, { weekday: 'short', day: 'numeric' })}
        </Typography.Text>
        <Flex vertical gap={2} style={{ marginTop: 4 }}>
          {list.slice(0, cap).map(chip)}
          {extra > 0 && (
            <Popover
              open={open === key}
              onOpenChange={(next) => {
                if (next) setOpen(key);
                else close(key);
              }}
              trigger="click"
              destroyOnHidden
              content={dayList(d, list)}
            >
              <Button
                ref={(node) => {
                  if (node === null) mores.current.delete(key);
                  else mores.current.set(key, node);
                }}
                type="link"
                size="small"
                style={{ padding: 0, height: 'auto', alignSelf: 'start' }}
                aria-label={t('incidents.calendar.more_on', { count: extra, day: fullDate })}
                aria-expanded={open === key}
                data-testid={`inc-cal-more-${key}`}
                onKeyDown={(event) => {
                  if (event.key === 'Escape' && open === key) {
                    event.stopPropagation();
                    close(key);
                  }
                }}
              >
                {t('incidents.calendar.more', { count: extra })}
              </Button>
            </Popover>
          )}
        </Flex>
      </div>
    );
  };

  const period = fmt(shown === 'month' ? anchor : (days[0] ?? anchor), {
    month: 'long',
    year: 'numeric',
  });
  const weekDays = days.slice(0, 7);

  return (
    <Flex vertical gap={8} data-testid="inc-calendar">
      <Flex gap={8} wrap align="center" justify="space-between">
        <Flex gap={4} align="center">
          <Button
            onClick={() => {
              goTo(dayOf(new Date().toISOString(), zone));
            }}
            data-testid="inc-cal-today"
          >
            {t('incidents.calendar.today')}
          </Button>
          <Button
            aria-label={t('incidents.calendar.previous')}
            onClick={() => {
              setAnchor(step(shown, anchor, -1));
            }}
            data-testid="inc-cal-prev"
          >
            {direction === 'rtl' ? '›' : '‹'}
          </Button>
          <Button
            aria-label={t('incidents.calendar.next')}
            onClick={() => {
              setAnchor(step(shown, anchor, 1));
            }}
            data-testid="inc-cal-next"
          >
            {direction === 'rtl' ? '‹' : '›'}
          </Button>
          <Typography.Text strong aria-live="polite" data-testid="inc-cal-period">
            {period}
          </Typography.Text>
        </Flex>
        <Segmented<Shown>
          aria-label={t('incidents.calendar.view')}
          value={shown}
          onChange={(value) => {
            setShown(value);
          }}
          options={[
            { value: 'month', label: t('incidents.calendar.month') },
            { value: 'week', label: t('incidents.calendar.week') },
          ]}
          data-testid="inc-cal-view"
        />
      </Flex>
      {noDue > 0 && (
        <Typography.Text type="secondary" data-testid="inc-cal-no-due">
          {t('incidents.calendar.no_due', { count: noDue })}
        </Typography.Text>
      )}
      {rows.length >= MOST && hasNextPage && (
        <Alert type="info" showIcon message={t('incidents.calendar.partial', { max: MOST })} />
      )}
      <div
        role="grid"
        aria-label={t('incidents.calendar.label', { period })}
        aria-busy={inRange.isFetching}
        onKeyDown={onKeyDown}
        style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))' }}
      >
        <div role="row" style={{ display: 'contents' }}>
          {weekDays.map((d) => (
            <div
              key={`head-${dayKey(d)}`}
              role="columnheader"
              style={{ paddingInline: 4, textAlign: 'center' }}
            >
              <Typography.Text type="secondary">
                {fmt(d, { weekday: wide ? 'short' : 'narrow' })}
              </Typography.Text>
            </div>
          ))}
        </div>
        {Array.from({ length: Math.ceil(days.length / 7) }, (_, week) => (
          <div key={`week-${String(week)}`} role="row" style={{ display: 'contents' }}>
            {days.slice(week * 7, week * 7 + 7).map(cell)}
          </div>
        ))}
      </div>
    </Flex>
  );
}
