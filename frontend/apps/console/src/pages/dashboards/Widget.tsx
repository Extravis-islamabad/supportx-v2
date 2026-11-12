import {
  AreaChartOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  BarChartOutlined,
  DashboardOutlined,
  ExpandOutlined,
  LineChartOutlined,
  NumberOutlined,
  PieChartOutlined,
  ReloadOutlined,
  TableOutlined,
} from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Card,
  Flex,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  theme,
  Tooltip,
  Typography,
} from 'antd';
import { useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';

import {
  queryKeys,
  useReportRun,
  type ChartType,
  type DashboardWidget,
  type ReportDefinition,
  type ReportResult,
} from '@supportx/api-client';
import { useIsolate, useJoinParts, useLabels } from '@supportx/labels';
import { TYPE } from '@supportx/ui';

import type { Drill } from '../reports/DrillDrawer';
import { ExportButton } from '../reports/exports';
import { useReportWords, type ReportWords } from '../reports/names';
import { Results } from '../reports/ReportPage';
import { kpiPeriod, previousPeriod, sparkline, trend, visibleTrend } from './kpi';
import { ROW_PX, widgetTitle } from './layout';

const CHART_ICONS: Record<ChartType, typeof BarChartOutlined> = {
  bar: BarChartOutlined,
  stacked_bar: BarChartOutlined,
  line: LineChartOutlined,
  area: AreaChartOutlined,
  doughnut: PieChartOutlined,
  gauge: DashboardOutlined,
  kpi: NumberOutlined,
  table: TableOutlined,
};

// Chart types a viewer may switch a widget to (REQ-DSH-015): for that viewer only.
const SWITCHABLE: ChartType[] = ['bar', 'stacked_bar', 'line', 'area', 'doughnut', 'table'];

export interface WidgetProps {
  widget: DashboardWidget;
  /** The definition to run for this viewer (filters and "me" applied); null: not available. */
  definition: ReportDefinition | null;
  /** Filters of the bar this widget cannot use ("not filtered by site", REQ-DSH-022 AC2). */
  unfiltered: string[];
  /** An open-now widget: the number of this moment, whatever the time filter (D-119). */
  now?: boolean;
  /** Filters of the bar this widget does use ("filtered by site"): it always says which. */
  filtered?: string[];
  onDrill: (drill: Drill) => void;
  /** Edit mode: the controls to move, resize and remove (REQ-DSH-019). */
  toolbar?: ReactNode;
  /** Free-form edit mode: the title is where a widget is grabbed to drag it. */
  dragHandle?: boolean;
}

/** One widget: a KPI tile or a chart, live, in the viewer's scope (REQ-DSH-007..016, 024). */
export function Widget({
  widget,
  definition,
  unfiltered,
  now = false,
  filtered = [],
  onDrill,
  toolbar,
  dragHandle = false,
}: WidgetProps) {
  const t = useLabels();
  const joinParts = useJoinParts();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [type, setType] = useState<ChartType | null>(null);
  const [expanded, setExpanded] = useState(false);
  const shown = useMemo(
    () => (definition && type ? { ...definition, chart: type } : definition),
    [definition, type],
  );
  const run = useReportRun(shown ?? undefined, shown !== null);
  const result = run.data;
  const words = useReportWords(result);
  const title = widgetTitle(widget, t);
  // No groupings means one number, except a created-vs-resolved report (its own buckets).
  const kpi =
    shown?.chart === 'kpi' || (shown !== null && shown.group_by?.length === 0 && !shown.flow);
  const ref = widget.report_ref;
  const report = ref?.startsWith('builtin:')
    ? `/reports/builtin/${ref.slice('builtin:'.length)}`
    : ref
      ? `/reports/${ref}`
      : null;

  const body =
    shown === null ? (
      <Typography.Text type="secondary">{t('dashboards.widget_unavailable')}</Typography.Text>
    ) : result === undefined ? (
      run.isError ? (
        <Typography.Text type="secondary">{t('dashboards.widget_failed')}</Typography.Text>
      ) : (
        <Spin />
      )
    ) : kpi ? (
      <KpiTile
        definition={shown}
        result={result}
        words={words}
        onDrill={() => {
          onDrill({ title, filter: result.drill_all, count: null, listPath: result.list_path });
        }}
      />
    ) : (
      <Results
        result={result}
        definition={shown}
        words={words}
        view={shown.chart === 'table' ? 'table' : 'chart'}
        chartHeight={Math.max(140, widget.place.h * ROW_PX - 110)}
        compact={widget.place.w <= 4}
        onDrill={(row) => {
          onDrill({
            title: `${title}: ${joinParts(row.keys.map((k, i) => (result.groups[i] ? words.key(result.groups[i], k) : '')))}`,
            filter: row.drill,
            count: typeof row.values[0] === 'number' ? row.values[0] : null,
            listPath: result.list_path,
          });
        }}
        onDrillAll={() => {
          onDrill({ title, filter: result.drill_all, count: null, listPath: result.list_path });
        }}
      />
    );

  return (
    <Card
      size="small"
      title={
        <span
          className={dragHandle ? 'dashboard-drag-handle' : undefined}
          style={dragHandle ? { cursor: 'move' } : undefined}
          data-testid={`widget-title-${widget.id}`}
        >
          {title}
        </span>
      }
      style={{ height: '100%', overflow: 'hidden' }}
      styles={{ body: { overflow: 'hidden', height: 'calc(100% - 40px)', padding: 0 } }}
      data-testid={`widget-${widget.id}`}
      extra={
        toolbar ?? (
          <Space size={2}>
            {run.isError && result !== undefined && (
              // A refresh failed: the numbers shown may be old (REQ-DSH-017).
              <Tag color="warning">{t('dashboards.stale')}</Tag>
            )}
            {!kpi && shown !== null && (
              <Select
                size="small"
                variant="borderless"
                aria-label={t('dashboards.switch_type')}
                value={shown.chart}
                onChange={(next) => {
                  setType(next);
                }}
                options={SWITCHABLE.map((c) => ({ value: c, label: t(`report_chart.${c}`) }))}
                // An icon of the current type, named for readers, so the title keeps its room
                // (QA WP-036 C2); the list still says each type in words.
                labelRender={({ value }) => {
                  const Icon = CHART_ICONS[value as ChartType];
                  return <Icon role="img" aria-label={t(`report_chart.${String(value)}`)} />;
                }}
                popupMatchSelectWidth={false}
                data-testid={`widget-type-${widget.id}`}
              />
            )}
            <Tooltip title={t('dashboards.refresh')}>
              <Button
                size="small"
                type="text"
                icon={<ReloadOutlined />}
                aria-label={t('dashboards.refresh')}
                onClick={() => {
                  void queryClient.invalidateQueries({
                    queryKey: queryKeys.reports.run(shown ?? undefined),
                  });
                }}
              />
            </Tooltip>
            <Tooltip title={t('dashboards.expand')}>
              <Button
                size="small"
                type="text"
                icon={<ExpandOutlined />}
                aria-label={t('dashboards.expand')}
                onClick={() => {
                  setExpanded(true);
                }}
                data-testid={`widget-expand-${widget.id}`}
              />
            </Tooltip>
          </Space>
        )
      }
    >
      {/* The content scrolls in a region named by the widget, so a keyboard can reach and
          scroll it (QA WP-036 BUG-05, axe scrollable-region-focusable). */}
      <div
        role="region"
        aria-label={title}
        tabIndex={0}
        style={{ height: '100%', overflow: 'auto', padding: 12 }}
      >
        {now && <Tag data-testid={`widget-now-${widget.id}`}>{t('dashboards.now')}</Tag>}
        {filtered.length > 0 && (
          <Tag data-testid={`widget-filtered-${widget.id}`}>
            {t('dashboards.filtered_by', {
              filters: filtered.map((f) => t(`dashboards.filter_${f}`)).join(' · '),
            })}
          </Tag>
        )}
        {unfiltered.length > 0 && (
          <Tag data-testid={`widget-unfiltered-${widget.id}`}>
            {t('dashboards.not_filtered_by', {
              filters: unfiltered.map((f) => t(`dashboards.filter_${f}`)).join(' · '),
            })}
          </Tag>
        )}
        {body}
      </div>
      <Modal
        open={expanded}
        title={title}
        width="min(1100px, 96vw)"
        footer={
          shown !== null && (
            <Flex gap={8} justify="end" wrap>
              {report && (
                <Button
                  onClick={() => {
                    void navigate(report);
                  }}
                >
                  {t('dashboards.open_as_report')}
                </Button>
              )}
              <ExportButton title={title} definition={shown} canRun />
            </Flex>
          )
        }
        onCancel={() => {
          setExpanded(false);
        }}
      >
        {/* Expanded: the same filters and drill-down (REQ-DSH-015 AC2), bigger. */}
        {shown !== null && result !== undefined && !kpi ? (
          <Results
            result={result}
            definition={shown}
            words={words}
            view="chart"
            chartHeight={420}
            onDrill={(row) => {
              setExpanded(false);
              onDrill({ title, filter: row.drill, count: null, listPath: result.list_path });
            }}
            onDrillAll={() => {
              setExpanded(false);
              onDrill({ title, filter: result.drill_all, count: null, listPath: result.list_path });
            }}
          />
        ) : (
          body
        )}
      </Modal>
    </Card>
  );
}

/** A KPI tile: the value, its trend against the previous period and a sparkline (REQ-DSH-008). */
function KpiTile({
  definition,
  result,
  words,
  onDrill,
}: {
  definition: ReportDefinition;
  result: ReportResult;
  words: ReportWords;
  onDrill: () => void;
}) {
  const t = useLabels();
  const { token } = theme.useToken();
  const isolate = useIsolate();
  const period = kpiPeriod(definition);
  const [now] = useState(() => new Date());
  const previous = useReportRun(
    period ? previousPeriod({ ...definition, group_by: [] }, period, now) : undefined,
    period !== null,
  );
  const spark = useReportRun(period ? sparkline(definition, period) : undefined, period !== null);
  const measure = result.measures[0];
  const value = result.totals[0];
  if (measure === undefined) return null;
  const raw = trend(
    typeof value === 'number' ? value : null,
    previous.data?.totals[0] ?? null,
    measure.better,
  );
  const moved = visibleTrend(raw, (n) => words.value(measure, n));
  const points = spark.data?.rows.map((r) => r.values[0] ?? null) ?? [];
  // The target's tile (UI pass 2): the measure on top, a 30 px number with its sparkline beside
  // it, and the change against the previous period below.
  const sparkColour =
    moved?.good === true
      ? token.colorSuccess
      : moved?.good === false
        ? token.colorError
        : token.colorPrimary;
  return (
    <Flex vertical gap={6} style={{ width: '100%' }}>
      <span style={{ fontSize: TYPE.meta, fontWeight: 600, color: token.colorTextSecondary }}>
        {words.measure(result.entity, measure.code).name}
      </span>
      <Flex align="flex-end" justify="space-between" gap={8}>
        <Typography.Link
          onClick={onDrill}
          style={{ fontSize: 30, fontWeight: 700, lineHeight: 1, letterSpacing: -0.5 }}
          data-testid="widget-kpi-value"
        >
          {words.value(measure, value)}
        </Typography.Link>
        {points.length > 1 && (
          <Sparkline points={points} colour={sparkColour} label={t('dashboards.sparkline')} />
        )}
      </Flex>
      {moved !== null && (
        <Typography.Text
          type={moved.good === null ? 'secondary' : moved.good ? 'success' : 'danger'}
          style={{ fontSize: TYPE.meta, fontWeight: 600 }}
          data-testid="widget-kpi-trend"
        >
          {moved.delta > 0 ? <ArrowUpOutlined /> : moved.delta < 0 ? <ArrowDownOutlined /> : null}{' '}
          {t(
            moved.good === null
              ? 'dashboards.trend_same'
              : moved.good
                ? 'dashboards.trend_good'
                : 'dashboards.trend_bad',
            { delta: isolate(words.value(measure, Math.abs(moved.delta))) },
          )}
        </Typography.Text>
      )}
    </Flex>
  );
}

/** A small trend line (88 x 30), drawn directly: a tile needs no chart engine for it. */
function Sparkline({
  points,
  colour,
  label,
}: {
  points: (number | null)[];
  colour: string;
  label: string;
}) {
  const values = points.map((p) => p ?? 0);
  const max = Math.max(...values, 1) * 1.05;
  const step = 84 / Math.max(values.length - 1, 1);
  const line = values
    .map((v, i) => `${(2 + i * step).toFixed(1)},${(27 - (v / max) * 24).toFixed(1)}`)
    .join(' ');
  return (
    <svg width={88} height={30} viewBox="0 0 88 30" role="img" aria-label={label}>
      <polyline
        points={line}
        fill="none"
        stroke={colour}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
