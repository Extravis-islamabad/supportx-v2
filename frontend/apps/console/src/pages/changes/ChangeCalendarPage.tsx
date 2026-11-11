import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Checkbox,
  DatePicker,
  Flex,
  Form,
  Modal,
  Segmented,
  Space,
  Switch,
  Typography,
  theme,
} from 'antd';
import type { Dayjs } from 'dayjs';
import { useMemo, useState, type DragEvent } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  calendarKeys,
  useChangeCalendar,
  useChangeWindows,
  useReapprovalPreview,
  useUpdateStagedSchedule,
  type CalendarEntry,
  type ChangeWindow,
} from '@supportx/api-client';
import { useListChannel, useTenantChannel } from '@supportx/realtime';
import {
  FilterBar,
  ListPage,
  PageHeader,
  ToneTag,
  useAccess,
  pickerFormat,
  useAppearance,
  useDateTime,
  useLabel,
  usePageCrumbs,
  useTimeZone,
} from '@supportx/ui';

import { labelled } from '../incidents/labels';
import { stageName } from '../staged/labels';
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

const VIEWS: CalendarView[] = ['month', 'week', 'day', 'agenda'];
const WEEK_START = { sunday: 0, monday: 1, saturday: 6 } as const;
const DRAG_TYPE = 'application/x-supportx-change-window';

interface Occurrence {
  window: ChangeWindow;
  starts_at: string;
  ends_at: string;
}

/**
 * The change calendar (WP-045c S3; ADR-042 §5): the changes you may see, by their implementation
 * window and planned downtimes, with the freeze and maintenance windows as layers, in month,
 * week, day and agenda views; days are wall-clock days in your zone. Live: a change moving or
 * a window changing shows at once. A change's window is dragged to another day to reschedule
 * it (same time of day), with the re-approval warning and the freeze guard of the record.
 */
export function ChangeCalendarPage() {
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
  const calendar = useChangeCalendar(range.start, range.end, mine);
  const windows = useChangeWindows(range);
  const update = useUpdateStagedSchedule('changes');
  const preview = useReapprovalPreview();
  usePageCrumbs([
    { label: t('nav.changes'), path: '/changes' },
    { label: t('changes.calendar.title') },
  ]);
  // Live: a change saved or moved (the changes list channel) and a window changed (broadcast).
  useListChannel('changes', () => {
    void queryClient.invalidateQueries({ queryKey: calendarKeys.all });
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
    const shown = view === 'month' ? anchor : first;
    return new Intl.DateTimeFormat(locale, {
      month: 'long',
      year: 'numeric',
      ...(view === 'month' ? {} : { day: 'numeric' }),
      timeZone: 'UTC',
    }).format(new Date(Date.UTC(shown.year, shown.month, shown.day)));
  })();
  const may = can('changes.edit');

  const reschedule = (entry: CalendarEntry, target: Day) => {
    const shift = daysBetween(dayOf(entry.starts_at, zone), target);
    if (shift === 0) return;
    const start = shiftDays(entry.starts_at, shift, zone);
    const end = shiftDays(entry.ends_at, shift, zone);
    const write = () => {
      update.mutate(
        {
          id: entry.record_id,
          stage: 'implementation',
          version: entry.version,
          body: { scheduled_start: start, scheduled_end: end },
        },
        {
          onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: calendarKeys.all });
          },
          onError: (error) => {
            const blocked = error instanceof ApiError && error.code === 'change_window_blocked';
            void modal.error({
              title: t(blocked ? 'errors.change_window_blocked' : 'changes.calendar.not_moved'),
              content: (
                <Link to={`/changes/${entry.record_id}?tab=schedule`}>
                  {t('changes.calendar.open_change', { id: entry.display_id })}
                </Link>
              ),
            });
          },
        },
      );
    };
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
  const [moveTo, setMoveTo] = useState<Dayjs | null>(null);

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
        <Link to={`/changes/${e.record_id}`} style={{ color: 'inherit' }}>
          <bdi dir="ltr" style={{ fontWeight: 600 }}>
            {e.display_id}
          </bdi>{' '}
          {e.kind === 'downtime'
            ? t('changes.calendar.downtime_of', { subject: e.subject })
            : e.subject}
        </Link>
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
      title={t('changes.calendar.title')}
      testId="calendar-header"
      extra={<Link to="/changes">{t('changes.calendar.list')}</Link>}
    />
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

  if (view === 'agenda') {
    const listed = days.filter(
      (d) =>
        entries.some((e) => touches(e.starts_at, e.ends_at, d, zone)) ||
        bands.some((o) => touches(o.starts_at, o.ends_at, d, zone)),
    );
    return (
      <ListPage testId="change-calendar" header={header} filters={filters}>
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
        </Flex>
      </ListPage>
    );
  }

  const columns = view === 'day' ? 1 : 7;
  const heads = days.slice(0, columns);
  return (
    <ListPage testId="change-calendar" header={header} filters={filters}>
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
            reschedule(moving, { year: moveTo.year(), month: moveTo.month(), day: moveTo.date() });
          }
          setMoving(undefined);
        }}
        data-testid="calendar-move"
      >
        <Form layout="vertical">
          <Form.Item label={t('changes.calendar.move_day')} htmlFor="calendar-move-day">
            <DatePicker
              id="calendar-move-day"
              value={moveTo}
              onChange={setMoveTo}
              format={pickerFormat(dates, false)}
              style={{ width: '100%' }}
              data-testid="calendar-move-day"
            />
          </Form.Item>
        </Form>
      </Modal>
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
    </ListPage>
  );
}
