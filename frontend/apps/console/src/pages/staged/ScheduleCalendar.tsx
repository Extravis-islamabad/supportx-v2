import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import {
  App,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Flex,
  Form,
  Modal,
  Segmented,
  Space,
  Switch,
  Typography,
  theme,
} from 'antd';
import { useMemo, useState, type DragEvent, type ReactNode } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  useChangeWindows,
  useReapprovalPreview,
  useUpdateStagedSchedule,
  type CalendarEntry,
  type ChangeWindow,
  type StagedPath,
} from '@supportx/api-client';
import { useListChannel, useTenantChannel } from '@supportx/realtime';
import {
  DateField,
  FilterBar,
  ListPage,
  PageHeader,
  ToneTag,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
  usePageCrumbs,
  useTimeZone,
} from '@supportx/ui';

import { labelled } from '../incidents/labels';
import { stageName, statusName } from './labels';
import {
  dayKey,
  dayOf,
  daysBetween,
  daysOf,
  normal,
  occurrences,
  rangeOf,
  shiftDays,
  step,
  touches,
  type CalendarView,
  type Day,
} from './calendarMath';

const VIEWS: CalendarView[] = ['month', 'week', 'day', 'agenda', 'timeline'];
const WEEK_START = { sunday: 0, monday: 1, saturday: 6 } as const;
const DRAG_TYPE = 'application/x-supportx-planned-window';

interface Occurrence {
  window: ChangeWindow;
  starts_at: string;
  ends_at: string;
}

/** What one staged type's calendar shows and how its windows move (WP-058b S1). */
export interface ScheduleKind {
  /** The record type's path: its list, records, permissions and list channel. */
  type: StagedPath;
  /** The stage whose window is on the calendar (the server's PLANNED_STAGE). */
  stage: string;
  /** The type's calendar query (permission-scoped on the server, per type). */
  useEntries: (start: string, end: string, mine: boolean) => UseQueryResult<CalendarEntry[]>;
  /** Its query key prefix, refetched when a record of the type changes. */
  queryKey: readonly string[];
  /** Whether a move asks the re-approval preview first (changes: ADR-042 §5). */
  preview: boolean;
  title: string;
  list: string;
  notMoved: string;
  testId: string;
}

/**
 * A staged type's calendar (WP-045c S3, generalised in WP-058b S1; ADR-042 §5): the records you
 * may see, by their planned stage's window and planned downtimes, with the freeze and maintenance
 * windows as layers, in month, week, day, agenda and timeline views; days are wall-clock days in
 * your zone. Live: a record moving or a window changing shows at once. A window is dragged to
 * another day, or moved by "Move…", to reschedule it (same time of day), through the record's
 * re-approval warning and conflict guard. A chip opens a quick view of its record.
 */
export function ScheduleCalendar({ kind }: { kind: ScheduleKind }) {
  const t = useLabel();
  const { locale, dates } = useAppearance();
  const { format } = useDateTime();
  const { can } = useAccess();
  const { modal } = App.useApp();
  const { token } = theme.useToken();
  const zone = useTimeZone();
  const queryClient = useQueryClient();
  const firstDay = WEEK_START[dates.weekStart];
  const [view, setView] = useState<CalendarView>('month');
  const [anchor, setAnchor] = useState<Day>(() => dayOf(new Date().toISOString(), zone));
  const [mine, setMine] = useState(false);
  const [layers, setLayers] = useState<string[]>(['freeze', 'maintenance']);
  const days = useMemo(() => daysOf(view, anchor, firstDay), [view, anchor, firstDay]);
  const range = useMemo(() => rangeOf(days, zone), [days, zone]);
  const calendar = kind.useEntries(range.start, range.end, mine);
  const windows = useChangeWindows(range);
  const update = useUpdateStagedSchedule(kind.type);
  const preview = useReapprovalPreview();
  const [quick, setQuick] = useState<CalendarEntry>();
  usePageCrumbs([
    { label: t(`nav.${kind.type}`), path: `/${kind.type}` },
    { label: t(kind.title) },
  ]);
  // Live: a record saved or moved (its list channel) and a window changed (broadcast).
  useListChannel(kind.type, () => {
    void queryClient.invalidateQueries({ queryKey: kind.queryKey });
  });
  useTenantChannel((m) => {
    if (m.type === 'work_items.change_windows_changed') void windows.refetch();
  });
  const entries = calendar.data ?? [];
  const bands: Occurrence[] = (windows.data ?? [])
    .filter((w) => layers.includes(w.kind))
    .flatMap((w) => occurrences(w, range.start, range.end).map((o) => ({ window: w, ...o })));
  const today = dayKey(dayOf(new Date().toISOString(), zone));
  const weekdayName = (d: Day) =>
    new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(
      new Date(Date.UTC(d.year, d.month, d.day)),
    );
  const dayName = (d: Day) =>
    new Intl.DateTimeFormat(locale, { day: 'numeric', timeZone: 'UTC' }).format(
      new Date(Date.UTC(d.year, d.month, d.day)),
    );
  const period = (() => {
    const first = days[0];
    if (first === undefined) return '';
    const whole = view === 'month' || view === 'timeline';
    const shown = whole ? anchor : first;
    return new Intl.DateTimeFormat(locale, {
      month: 'long',
      year: 'numeric',
      ...(whole ? {} : { day: 'numeric' }),
      timeZone: 'UTC',
    }).format(new Date(Date.UTC(shown.year, shown.month, shown.day)));
  })();
  const may = can(`${kind.type}.edit`);

  const reschedule = (entry: CalendarEntry, target: Day) => {
    const shift = daysBetween(dayOf(entry.starts_at, zone), target);
    if (shift === 0) return;
    const start = shiftDays(entry.starts_at, shift, zone);
    const end = shiftDays(entry.ends_at, shift, zone);
    const write = () => {
      update.mutate(
        {
          id: entry.record_id,
          stage: kind.stage,
          version: entry.version,
          body: { scheduled_start: start, scheduled_end: end },
        },
        {
          onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: kind.queryKey });
          },
          onError: (error) => {
            const blocked = error instanceof ApiError && error.code === 'change_window_blocked';
            void modal.error({
              title: t(blocked ? 'errors.change_window_blocked' : kind.notMoved),
              content: (
                <Link to={`/${kind.type}/${entry.record_id}?tab=schedule`}>
                  {t('changes.calendar.open_change', { id: entry.display_id })}
                </Link>
              ),
            });
          },
        },
      );
    };
    if (!kind.preview) {
      write();
      return;
    }
    preview.mutate(
      { id: entry.record_id, body: { window_start: start, window_end: end } },
      {
        onSuccess: (found) => {
          const back = found.filter((s) => s.changes.some((c) => c.effect === 'restart'));
          if (back.length === 0) {
            write();
            return;
          }
          void modal.confirm({
            title: t('changes.reapproval.title'),
            okText: t('changes.reapproval.confirm'),
            content: (
              <Flex vertical gap={4} data-testid="calendar-reapproval">
                <Typography.Text>{t('changes.window.reapproval_warning')}</Typography.Text>
                {back.map((s) => (
                  <Typography.Text key={s.stage} strong>
                    {stageName(t, s.stage)}
                  </Typography.Text>
                ))}
              </Flex>
            ),
            onOk: write,
          });
        },
        onError: write,
      },
    );
  };

  // The keyboard's way to reschedule (lane C's #381 review): "Move…" asks for the new day and
  // goes through the same reschedule, conflict check and re-approval as a drag.
  const [moving, setMoving] = useState<CalendarEntry>();
  const [moveTo, setMoveTo] = useState<string | null>(null); // a day, YYYY-MM-DD

  const onDrop = (event: DragEvent<HTMLDivElement>, target: Day) => {
    event.preventDefault();
    const raw = event.dataTransfer.getData(DRAG_TYPE);
    const entry = entries.find((e) => `${e.record_id}:${e.kind}` === raw);
    if (entry !== undefined) reschedule(entry, target);
  };

  const entryChip = (e: CalendarEntry) => {
    const draggable = may && e.kind === 'window';
    return (
      <div
        key={`${e.record_id}:${e.kind}:${e.part_id ?? ''}`}
        draggable={draggable}
        onDragStart={(event) => {
          event.dataTransfer.setData(DRAG_TYPE, `${e.record_id}:${e.kind}`);
          event.dataTransfer.effectAllowed = 'move';
        }}
        data-testid={`calendar-entry-${e.display_id}-${e.kind}`}
        style={{
          borderInlineStart: `3px ${e.kind === 'window' ? 'solid' : 'dashed'} ${token.colorPrimary}`,
          paddingInline: 6,
          paddingBlock: 2,
          marginBottom: 2,
          background: token.colorFillTertiary,
          borderRadius: token.borderRadiusSM,
          cursor: draggable ? 'grab' : undefined,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={`${e.display_id} ${e.subject}`}
      >
        {/* A quick view first (WP-058b S1); the drawer links to the record. */}
        <Button
          type="link"
          size="small"
          style={{ color: 'inherit', padding: 0, height: 'auto', maxWidth: '100%' }}
          onClick={() => {
            setQuick(e);
          }}
          data-testid={`calendar-open-${e.display_id}-${e.kind}`}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
            <bdi dir="ltr" style={{ fontWeight: 600 }}>
              {e.display_id}
            </bdi>{' '}
            {e.kind === 'downtime'
              ? t('changes.calendar.downtime_of', { subject: e.subject })
              : e.subject}
          </span>
        </Button>
        {draggable && (
          <Button
            size="small"
            type="link"
            style={{ paddingInline: 4, height: 'auto' }}
            onClick={() => {
              setMoving(e);
              setMoveTo(null);
            }}
            aria-label={t('changes.calendar.move_of', { id: e.display_id })}
            data-testid={`calendar-move-${e.display_id}`}
          >
            {t('changes.calendar.move')}
          </Button>
        )}
      </div>
    );
  };

  const bandTag = (o: Occurrence, index: number) => (
    <ToneTag
      key={`${o.window.id}-${String(index)}`}
      tone={o.window.kind === 'freeze' ? 'error' : 'info'}
      testId={`calendar-window-${o.window.id}`}
    >
      {labelled(o.window.labels, locale, () => o.window.name)}
    </ToneTag>
  );

  const dayCell = (d: Day, compact: boolean) => {
    const key = dayKey(d);
    const mineToday = entries.filter((e) => touches(e.starts_at, e.ends_at, d, zone));
    const bandsToday = bands.filter((o) => touches(o.starts_at, o.ends_at, d, zone));
    const outside = view === 'month' && d.month !== normal(anchor).month;
    return (
      <div
        key={key}
        role="gridcell"
        aria-label={new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeZone: 'UTC' }).format(
          new Date(Date.UTC(d.year, d.month, d.day)),
        )}
        data-testid={`calendar-day-${key}`}
        onDragOver={(event) => {
          if (may) event.preventDefault();
        }}
        onDrop={(event) => {
          onDrop(event, d);
        }}
        style={{
          minHeight: compact ? 110 : 320,
          padding: 6,
          border: `1px solid ${token.colorBorderSecondary}`,
          // Out of the month: a quieter background and secondary text, never opacity, so its
          // chips keep their contrast (lane C's #381 review).
          background:
            key === today
              ? token.colorPrimaryBg
              : outside
                ? token.colorFillQuaternary
                : token.colorBgContainer,
          minWidth: 0,
        }}
      >
        <Typography.Text strong={key === today} type={outside ? 'secondary' : undefined}>
          {view === 'month' ? dayName(d) : `${weekdayName(d)} ${dayName(d)}`}
        </Typography.Text>
        <Flex vertical gap={2} style={{ marginTop: 4 }}>
          {bandsToday.length > 0 && (
            <Space size={2} wrap>
              {bandsToday.map(bandTag)}
            </Space>
          )}
          {mineToday.map(entryChip)}
        </Flex>
      </div>
    );
  };

  const header = (
    <PageHeader
      title={t(kind.title)}
      testId="calendar-header"
      extra={<Link to={`/${kind.type}`}>{t(kind.list)}</Link>}
    />
  );
  const quickView = (
    <Drawer
      open={quick !== undefined}
      onClose={() => {
        setQuick(undefined);
      }}
      title={quick === undefined ? '' : <bdi dir="ltr">{quick.display_id}</bdi>}
      width={380}
      data-testid="calendar-quick"
    >
      {quick !== undefined && (
        <Flex vertical gap={12}>
          <Typography.Text strong>{quick.subject}</Typography.Text>
          <Descriptions
            column={1}
            size="small"
            items={[
              {
                key: 'stage',
                label: t('changes.calendar.quick.stage'),
                children: stageName(t, quick.stage),
              },
              {
                key: 'status',
                label: t('changes.calendar.quick.status'),
                children: statusName(t, quick.status),
              },
              {
                key: 'when',
                label: t(
                  quick.kind === 'downtime'
                    ? 'changes.calendar.quick.downtime'
                    : 'changes.calendar.quick.window',
                ),
                children: `${format(quick.starts_at)} – ${format(quick.ends_at)}`,
              },
            ]}
          />
          <Link to={`/${kind.type}/${quick.record_id}`} data-testid="calendar-quick-open">
            {t('changes.calendar.quick.open', { id: quick.display_id })}
          </Link>
        </Flex>
      )}
    </Drawer>
  );
  // The keyboard's Move… works in every view, so its dialog sits on the page.
  const moveDialog = (
    <Modal
      open={moving !== undefined}
      title={moving ? t('changes.calendar.move_title', { id: moving.display_id }) : ''}
      okText={t('changes.calendar.move_ok')}
      okButtonProps={{ disabled: moveTo === null, 'data-testid': 'calendar-move-ok' }}
      onCancel={() => {
        setMoving(undefined);
      }}
      onOk={() => {
        if (moving !== undefined && moveTo !== null) {
          const [year = 0, month = 1, day = 1] = moveTo.split('-').map(Number);
          reschedule(moving, { year, month: month - 1, day });
        }
        setMoving(undefined);
      }}
      data-testid="calendar-move"
    >
      <Form layout="vertical">
        <Form.Item label={t('changes.calendar.move_day')} htmlFor="calendar-move-day">
          {/* The shared day field (lane A's WP-058b condition). */}
          <DateField
            id="calendar-move-day"
            value={moveTo}
            onChange={setMoveTo}
            testId="calendar-move-day"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
  const page = (children: ReactNode) => (
    <ListPage testId={kind.testId} header={header} filters={filters}>
      {quickView}
      {moveDialog}
      {children}
    </ListPage>
  );
  const filters = (
    <FilterBar
      testId="calendar-filters"
      view={
        <Segmented<CalendarView>
          value={view}
          onChange={setView}
          options={VIEWS.map((v) => ({ value: v, label: t(`changes.calendar.view.${v}`) }))}
          data-testid="calendar-view"
        />
      }
      search={
        <Space wrap>
          <Button
            icon={<LeftOutlined aria-hidden />}
            aria-label={t('changes.calendar.previous')}
            onClick={() => {
              setAnchor((a) => normal(step(view, a, -1)));
            }}
            data-testid="calendar-previous"
          />
          <Button
            onClick={() => {
              setAnchor(dayOf(new Date().toISOString(), zone));
            }}
            data-testid="calendar-today"
          >
            {t('changes.calendar.today')}
          </Button>
          <Button
            icon={<RightOutlined aria-hidden />}
            aria-label={t('changes.calendar.next')}
            onClick={() => {
              setAnchor((a) => normal(step(view, a, 1)));
            }}
            data-testid="calendar-next"
          />
          <Typography.Text strong data-testid="calendar-period">
            {period}
          </Typography.Text>
        </Space>
      }
      extra={
        <Space wrap>
          <Space size={4}>
            <Switch
              size="small"
              checked={mine}
              onChange={setMine}
              aria-label={t('changes.calendar.mine')}
              data-testid="calendar-mine"
            />
            <Typography.Text>{t('changes.calendar.mine')}</Typography.Text>
          </Space>
          <Checkbox.Group
            value={layers}
            onChange={(v) => {
              setLayers(v);
            }}
            options={[
              { value: 'freeze', label: t('change_window_kind.freeze') },
              { value: 'maintenance', label: t('change_window_kind.maintenance') },
            ]}
            data-testid="calendar-layers"
          />
        </Space>
      }
    />
  );

  // The timeline (WP-058b S1): one row per record across the month's days, each window a bar
  // from its first day to its last; the freeze and maintenance windows on their own row.
  const timeline = () => {
    // Its columns (the label is column 1) and its own line in the row, so bars never overlap.
    const span = (from: string, to: string, line: number) => {
      const first = days.findIndex((d) => touches(from, to, d, zone));
      if (first < 0) return undefined;
      let last = first;
      for (const d of days.slice(first + 1)) {
        if (!touches(from, to, d, zone)) break;
        last += 1;
      }
      return { gridColumn: `${String(first + 2)} / ${String(last + 3)}`, gridRow: line + 1 };
    };
    const records = [...new Map(entries.map((e) => [e.record_id, e])).values()];
    const gridColumns = `minmax(140px, 200px) repeat(${String(days.length)}, minmax(28px, 1fr))`;
    const row = (key: string, label: ReactNode, cells: ReactNode, lines = 1) => (
      <div
        key={key}
        role="row"
        style={{
          display: 'grid',
          gridTemplateColumns: gridColumns,
          alignItems: 'center',
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          minHeight: 36,
        }}
      >
        <div
          role="rowheader"
          style={{
            padding: 6,
            minWidth: 0,
            overflow: 'hidden',
            gridColumn: 1,
            gridRow: `1 / span ${String(lines)}`,
          }}
        >
          {label}
        </div>
        {cells}
      </div>
    );
    return (
      <div role="region" aria-label={t(kind.title)} tabIndex={0} style={{ overflowX: 'auto' }}>
        <div
          role="grid"
          aria-label={period}
          data-testid="calendar-timeline"
          style={{ minWidth: 200 + days.length * 28 }}
        >
          {row(
            'head',
            <Typography.Text type="secondary">
              {t('changes.calendar.timeline.record')}
            </Typography.Text>,
            days.map((d) => (
              <div
                key={dayKey(d)}
                role="columnheader"
                aria-label={new Intl.DateTimeFormat(locale, {
                  dateStyle: 'full',
                  timeZone: 'UTC',
                }).format(new Date(Date.UTC(d.year, d.month, d.day)))}
                style={{
                  textAlign: 'center',
                  background: dayKey(d) === today ? token.colorPrimaryBg : undefined,
                }}
              >
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {dayName(d)}
                </Typography.Text>
              </div>
            )),
          )}
          {bands.length > 0 &&
            row(
              'windows',
              <Typography.Text type="secondary">
                {t('changes.calendar.timeline.windows')}
              </Typography.Text>,
              bands.map((o, i) => {
                const where = span(o.starts_at, o.ends_at, i);
                return where === undefined ? null : (
                  <div
                    key={`${o.window.id}-${String(i)}`}
                    role="gridcell"
                    style={{ ...where, minWidth: 0 }}
                  >
                    {bandTag(o, i)}
                  </div>
                );
              }),
              bands.length,
            )}
          {records.length === 0 && (
            <Typography.Text type="secondary" style={{ display: 'block', padding: 12 }}>
              {t('changes.calendar.nothing')}
            </Typography.Text>
          )}
          {records.map((r) => {
            const own = entries.filter((e) => e.record_id === r.record_id);
            return row(
              r.record_id,
              <Typography.Text ellipsis={{ tooltip: r.subject }}>
                <bdi dir="ltr" style={{ fontWeight: 600 }}>
                  {r.display_id}
                </bdi>{' '}
                {r.subject}
              </Typography.Text>,
              own.map((e, i) => {
                const where = span(e.starts_at, e.ends_at, i);
                return where === undefined ? null : (
                  <div
                    key={`${e.kind}:${e.part_id ?? ''}`}
                    role="gridcell"
                    style={{ ...where, minWidth: 0 }}
                    data-testid={`timeline-${e.display_id}-${e.kind}`}
                  >
                    {entryChip(e)}
                  </div>
                );
              }),
              own.length,
            );
          })}
        </div>
      </div>
    );
  };

  if (view === 'agenda') {
    const listed = days.filter(
      (d) =>
        entries.some((e) => touches(e.starts_at, e.ends_at, d, zone)) ||
        bands.some((o) => touches(o.starts_at, o.ends_at, d, zone)),
    );
    return page(
      <Flex vertical gap={12} data-testid="calendar-agenda">
        {listed.length === 0 && (
          <Typography.Text type="secondary">{t('changes.calendar.nothing')}</Typography.Text>
        )}
        {listed.map((d) => (
          <div key={dayKey(d)} data-testid={`calendar-day-${dayKey(d)}`}>
            <Typography.Title level={5}>
              {new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeZone: 'UTC' }).format(
                new Date(Date.UTC(d.year, d.month, d.day)),
              )}
            </Typography.Title>
            <Space size={2} wrap>
              {bands.filter((o) => touches(o.starts_at, o.ends_at, d, zone)).map(bandTag)}
            </Space>
            {entries
              .filter((e) => touches(e.starts_at, e.ends_at, d, zone))
              .map((e) => (
                <Flex key={`${e.record_id}:${e.kind}:${e.part_id ?? ''}`} gap={8} wrap>
                  <span
                    style={{ whiteSpace: 'nowrap' }}
                  >{`${format(e.starts_at)} – ${format(e.ends_at)}`}</span>
                  {entryChip(e)}
                </Flex>
              ))}
          </div>
        ))}
      </Flex>,
    );
  }

  if (view === 'timeline') return page(timeline());

  const columns = view === 'day' ? 1 : 7;
  const heads = days.slice(0, columns);
  return page(
    <>
      <div
        role="region"
        aria-label={t('changes.calendar.title')}
        tabIndex={0}
        style={{ overflowX: 'auto' }}
      >
        <div
          role="grid"
          aria-label={period}
          data-testid={`calendar-${view}`}
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${String(columns)}, minmax(110px, 1fr))`,
            minWidth: columns === 7 ? 770 : undefined,
          }}
        >
          {/* Rows for the grid's roles (axe: aria-required-children); `display: contents`
              keeps the CSS grid (lane C's #381 review). */}
          {view === 'month' && (
            <div role="row" style={{ display: 'contents' }}>
              {heads.map((d) => (
                <div key={`head-${dayKey(d)}`} role="columnheader" style={{ padding: 6 }}>
                  <Typography.Text type="secondary">{weekdayName(d)}</Typography.Text>
                </div>
              ))}
            </div>
          )}
          {Array.from({ length: Math.ceil(days.length / columns) }, (_, week) => (
            <div key={`row-${String(week)}`} role="row" style={{ display: 'contents' }}>
              {days
                .slice(week * columns, (week + 1) * columns)
                .map((d) => dayCell(d, view === 'month'))}
            </div>
          ))}
        </div>
      </div>
    </>,
  );
}
