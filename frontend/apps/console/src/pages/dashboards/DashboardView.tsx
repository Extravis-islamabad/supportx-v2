import {
  ArrowDownOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  ArrowUpOutlined,
  ColumnHeightOutlined,
  ColumnWidthOutlined,
  DeleteOutlined,
  MinusOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  ConfigProvider,
  Flex,
  Grid,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { lazy, Suspense, useContext, useMemo, useState } from 'react';

import {
  useReportEntity,
  useReportLibrary,
  useSession,
  useStructure,
  type Dashboard,
  type DashboardBody,
  type DashboardFilters,
  type DashboardWidget,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { useRealtimeStatus } from '@supportx/realtime';

import { DrillDrawer, type Drill } from '../reports/DrillDrawer';
import { useLiveReportRefresh } from '../reports/liveRefresh';
import { AddWidget } from './AddWidget';
import { unusableFilters, widgetDefinition } from './widgetDefinition';
import {
  adjust,
  COLUMNS,
  normalBody,
  readingOrder,
  settle,
  ROW_PX,
  widgetTitle,
  type Body,
  type Place,
} from './layout';
import { Widget } from './Widget';

const DAYS = [7, 30, 90, 365] as const;
// Only editors download the grid library (D-110).
const FreeGrid = lazy(() => import('./FreeGrid').then((m) => ({ default: m.FreeGrid })));

/**
 * A dashboard on screen (REQ-DSH-016, 019, 022, 024): the filter bar, the grid of live widgets,
 * and, for those who may edit it, edit mode. `editing` / `onSave` come from the page.
 */
export function DashboardView({
  dashboard,
  editing,
  onDone,
  onCancel,
}: {
  dashboard: Dashboard;
  editing: boolean;
  /** Leaving edit mode saves the layout (REQ-DSH-019). */
  onDone: (body: DashboardBody) => void;
  onCancel: () => void;
}) {
  const t = useLabels();
  const session = useSession().data;
  const library = useReportLibrary();
  const entity = useReportEntity('incident');
  const sites = useStructure('sites', true, true);
  const groups = useStructure('groups', true, true);
  const status = useRealtimeStatus();
  const screens = Grid.useBreakpoint();
  const { direction } = useContext(ConfigProvider.ConfigContext);
  const narrow = !screens.md;
  // The viewer's filters for this visit; the owner's defaults are where they start (DSH-022).
  const [filters, setFilters] = useState<DashboardFilters>(dashboard.body.filters ?? {});
  const [drill, setDrill] = useState<Drill | null>(null);
  // Edit mode: the draft and its undo history (REQ-DSH-019 AC3).
  const saved = normalBody(dashboard.body);
  const [history, setHistory] = useState<Body[]>([]);
  const [draft, setDraft] = useState<Body>(saved);
  const body = editing ? draft : saved;
  const fields = entity.data?.fields;

  // Every widget on screen refreshes when the list it counts changes, at most once a second.
  useLiveReportRefresh('incidents');

  const change = (next: Body) => {
    setHistory((past) => [...past, draft]);
    setDraft(next);
  };
  const moveWidget = (id: string, place: Partial<Place>) => {
    // Keyboard moves follow the free grid's rules: nothing is left on top of anything.
    const next = draft.widgets.map((w) =>
      w.id === id ? { ...w, place: adjust(w.place, place) } : w,
    );
    change({ ...draft, widgets: settle(next, id) });
  };
  const userId = session?.user.id ?? '';
  const ordered = narrow ? readingOrder(body.widgets) : body.widgets;
  const definitions = useMemo(
    () =>
      new Map(
        body.widgets.map((w) => [
          w.id,
          widgetDefinition(w, { userId, filters, builtin: library.data?.builtin, fields }),
        ]),
      ),
    [body.widgets, userId, filters, library.data?.builtin, fields],
  );

  const renderWidget = (widget: DashboardWidget, handle: boolean) => (
    <Widget
      widget={widget}
      definition={definitions.get(widget.id) ?? null}
      unfiltered={unusableFilters(filters, fields)}
      onDrill={setDrill}
      toolbar={editing ? toolbar(widget) : undefined}
      dragHandle={handle}
    />
  );

  const toolbar = (widget: DashboardWidget) => {
    const name = widgetTitle(widget, t);
    const button = (key: string, icon: React.ReactNode, onClick: () => void, disabled = false) => (
      <Tooltip key={key} title={t(`dashboards.${key}`)}>
        <Button
          size="small"
          type="text"
          icon={icon}
          disabled={disabled}
          aria-label={t(`dashboards.${key}_named`, { name })}
          onClick={onClick}
          data-testid={`widget-${key}-${widget.id}`}
        />
      </Tooltip>
    );
    const p = widget.place;
    // Each control as its own small step; arrows move by one column or row (REQ-DSH-019 AC2).
    const controls: [string, React.ReactNode, Partial<Place> | null, boolean][] = [
      ['move_left', <ArrowLeftOutlined key="l" />, { x: p.x - 1 }, p.x === 0],
      ['move_right', <ArrowRightOutlined key="r" />, { x: p.x + 1 }, p.x + p.w >= COLUMNS],
      ['move_up', <ArrowUpOutlined key="u" />, { y: p.y - 1 }, p.y === 0],
      ['move_down', <ArrowDownOutlined key="d" />, { y: p.y + 1 }, false],
      ['narrower', <MinusOutlined key="n" />, { w: p.w - 1 }, p.w <= 1],
      ['wider', <ColumnWidthOutlined key="w" />, { w: p.w + 1 }, p.x + p.w >= COLUMNS],
      ['taller', <ColumnHeightOutlined key="t" />, { h: p.h + 1 }, p.h >= 12],
      ['shorter', <PlusOutlined key="s" rotate={45} />, { h: p.h - 1 }, p.h <= 1],
      ['remove', <DeleteOutlined key="x" />, null, false],
    ];
    return (
      <Space size={0} wrap>
        {controls.map(([key, icon, place, disabled]) =>
          button(
            key,
            icon,
            () => {
              if (place) moveWidget(widget.id, place);
              else change({ ...draft, widgets: draft.widgets.filter((w) => w.id !== widget.id) });
            },
            disabled,
          ),
        )}
      </Space>
    );
  };

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Flex wrap gap={8} align="center">
        <Select
          allowClear
          style={{ minWidth: 180 }}
          aria-label={t('dashboards.filter_site_id')}
          placeholder={t('dashboards.all_sites')}
          value={filters.site_id ?? undefined}
          onChange={(value?: string) => {
            setFilters({ ...filters, site_id: value ?? null });
          }}
          options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
          data-testid="dashboard-filter-site"
        />
        <Select
          allowClear
          style={{ minWidth: 180 }}
          aria-label={t('dashboards.filter_group_id')}
          placeholder={t('dashboards.all_groups')}
          value={filters.group_id ?? undefined}
          onChange={(value?: string) => {
            setFilters({ ...filters, group_id: value ?? null });
          }}
          options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
          data-testid="dashboard-filter-group"
        />
        <Select
          allowClear
          style={{ minWidth: 160 }}
          aria-label={t('dashboards.filter_days')}
          placeholder={t('dashboards.any_time')}
          value={filters.days ?? undefined}
          onChange={(value?: number) => {
            setFilters({ ...filters, days: value ?? null });
          }}
          options={DAYS.map((d) => ({ value: d, label: t('dashboards.last_days', { count: d }) }))}
          data-testid="dashboard-filter-days"
        />
        {status !== 'connected' && (
          // The live connection is down: numbers refresh on a timer meanwhile (REQ-DSH-017).
          <Tag color="warning" data-testid="dashboard-connection">
            {t(`dashboards.connection_${status === 'polling' ? 'polling' : 'reconnecting'}`)}
          </Tag>
        )}
        <Typography.Text type="secondary">{t('reports.scope_note')}</Typography.Text>
      </Flex>
      {editing && (
        <Alert
          type="info"
          showIcon
          message={t('dashboards.editing')}
          description={t('dashboards.editing_hint')}
          action={
            <Space wrap>
              <AddWidget
                taken={draft.widgets.map((w) => w.id)}
                below={Math.max(0, ...draft.widgets.map((w) => w.place.y + w.place.h))}
                onAdd={(widget) => {
                  change({ ...draft, widgets: [...draft.widgets, widget] });
                }}
              />
              <Button
                disabled={history.length === 0}
                onClick={() => {
                  setDraft(history.at(-1) ?? draft);
                  setHistory((past) => past.slice(0, -1));
                }}
                data-testid="dashboard-undo"
              >
                {t('dashboards.undo')}
              </Button>
              <Button
                onClick={() => {
                  setDraft(saved);
                  setHistory([]);
                  onCancel();
                }}
              >
                {t('reports.cancel')}
              </Button>
              <Button
                type="primary"
                onClick={() => {
                  onDone(draft);
                  setHistory([]);
                }}
                data-testid="dashboard-done"
              >
                {t('dashboards.done')}
              </Button>
            </Space>
          }
        />
      )}
      {body.widgets.length === 0 && (
        <Typography.Paragraph type="secondary">{t('dashboards.empty')}</Typography.Paragraph>
      )}
      {editing && !narrow ? (
        // Edit mode: free-form drag and resize, loaded only now (D-110); the keyboard buttons
        // stay on every widget (REQ-DSH-019 AC2).
        <Suspense fallback={<Spin />}>
          <FreeGrid
            widgets={body.widgets}
            rtl={direction === 'rtl'}
            render={(widget) => renderWidget(widget, true)}
            onPlaces={(places) => {
              const moved = draft.widgets.map((w) => ({
                ...w,
                place: places.get(w.id) ?? w.place,
              }));
              if (JSON.stringify(moved) !== JSON.stringify(draft.widgets)) {
                change({ ...draft, widgets: moved });
              }
            }}
          />
        </Suspense>
      ) : (
        <div
          // A 12-column grid; in right to left the columns start on the right (CSS grid follows
          // the page direction). Narrow screens stack the widgets in reading order (REQ-DSH-019
          // AC4); editing there uses the buttons.
          style={
            narrow
              ? { display: 'flex', flexDirection: 'column', gap: 12 }
              : {
                  display: 'grid',
                  gridTemplateColumns: `repeat(${String(COLUMNS)}, minmax(0, 1fr))`,
                  gridAutoRows: ROW_PX,
                  gap: 12,
                }
          }
          data-testid="dashboard-grid"
        >
          {ordered.map((widget) => {
            const p = widget.place;
            return (
              <div
                key={widget.id}
                style={
                  narrow
                    ? { height: p.h * ROW_PX }
                    : {
                        gridColumn: `${String(p.x + 1)} / span ${String(p.w)}`,
                        gridRow: `${String(p.y + 1)} / span ${String(p.h)}`,
                        minWidth: 0,
                      }
                }
              >
                {renderWidget(widget, false)}
              </div>
            );
          })}
        </div>
      )}
      <DrillDrawer
        drill={drill}
        onClose={() => {
          setDrill(null);
        }}
      />
    </Space>
  );
}
