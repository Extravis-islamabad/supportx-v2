import { InfoCircleOutlined, StarFilled, StarOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Flex,
  Input,
  Modal,
  Result,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tooltip,
  Typography,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  ApiError,
  useCreateReport,
  useDeleteReport,
  useIncidentCatalogue,
  useReportEntity,
  useReportLibrary,
  useReportRun,
  useSavedReport,
  useStarReport,
  useUpdateReport,
  type ChartType,
  type DateBucket,
  type ReportDefinition,
  type ReportField,
  type ReportResult,
  type ReportRow,
  type SavedReport,
} from '@supportx/api-client';
import { Chart, kitOption } from '@supportx/charts';
import {
  FilterBuilder,
  fromDsl,
  rowProblems,
  toDsl,
  type FilterFieldOption,
  type FilterModel,
  type FilterValueType,
} from '@supportx/forms';
import {
  useIsolate,
  useJoinParts,
  useLabels,
  useListFormat,
  type ListKind,
} from '@supportx/labels';
import {
  ConflictDialog,
  reportError,
  FormProblem,
  describeError,
  lengthLimit,
  NoAccess,
  useAccess,
  useConflict,
  useConflictRetry,
  useFormProblem,
  useDateTime,
  WriteButton,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { PRIORITY_COLOURS } from '../incidents/priorityColours';
import { DrillDrawer, type Drill } from './DrillDrawer';
import { ExportButton, MyExportsButton } from './exports';
import { useLiveReportRefresh } from './liveRefresh';
import { ScheduleButton } from './schedules';
import { INCIDENT_REPORT_FIELDS, useReportWords, type ReportWords } from './names';

const CHARTS: ChartType[] = [
  'bar',
  'stacked_bar',
  'line',
  'area',
  'doughnut',
  'gauge',
  'kpi',
  'table',
];
const BUCKETS: DateBucket[] = ['day', 'week', 'month', 'quarter', 'year', 'age'];
const RUN_DELAY_MS = 400;

interface Base {
  ref: string;
  name: string;
  description: string;
  definition: ReportDefinition;
  builtin: string | null;
  saved: { id: string; version: number; canEdit: boolean } | null;
}

function savedBase(report: SavedReport): Base {
  return {
    ref: report.id,
    name: report.name,
    description: report.description ?? '',
    definition: report.definition,
    builtin: null,
    saved: { id: report.id, version: report.version, canEdit: report.can_edit },
  };
}

// A saved report's definition by the names this screen gives its parts (QA WP-029 BUG-05).
const DEFINITION_PARTS: Record<string, string> = {
  chart: 'reports.chart',
  filter: 'reports.filters',
  group_by: 'reports.group_by',
  measures: 'reports.measures',
};

/** /reports/builtin/:code and /reports/:id: the report viewer (REQ-RPT-050). */
export function ReportPage() {
  const t = useLabels();
  const { code, id } = useParams();
  const { can } = useAccess();
  const allowed = can('reports.view');
  const library = useReportLibrary(allowed && code !== undefined);
  const saved = useSavedReport(allowed ? id : undefined);

  const base = useMemo<Base | null>(() => {
    if (code !== undefined) {
      const builtin = library.data?.builtin.find((r) => r.code === code);
      return builtin
        ? {
            ref: `builtin:${builtin.code}`,
            name: t(`report.${builtin.code}`),
            description: t(`report.${builtin.code}.description`),
            definition: builtin.definition,
            builtin: builtin.code,
            saved: null,
          }
        : null;
    }
    const report = saved.data;
    return report ? savedBase(report) : null;
  }, [code, library.data, saved.data, t]);

  if (!allowed) return <NoAccess titleKey="nav.reports" />;
  const loading = code !== undefined ? library.isPending : saved.isPending;
  if (base === null) {
    return loading ? null : <Result status="404" title={t('errors.report_not_found')} />;
  }
  // Keyed by report: another report starts from its definition; a newer save of this one is
  // taken by the view itself (kept edits meet it in the conflict dialog, QA WP-029 BUG-05).
  return <ReportView key={base.ref} latest={base} />;
}

function fieldType(type: string): FilterValueType {
  return (
    (['string', 'enum', 'uuid', 'datetime', 'integer', 'boolean', 'decimal', 'date'] as const).find(
      (known) => known === type,
    ) ?? 'string'
  );
}

function ReportView({ latest }: { latest: Base }) {
  const t = useLabels();
  const isolate = useIsolate();
  // The report as this view opened it: its definition is what "changed" compares with.
  const [base, setBase] = useState(latest);
  const navigate = useNavigate();
  const { can } = useAccess();
  const dates = useDateTime();
  const entity = useReportEntity(base.definition.entity);
  const [draft, setDraft] = useState<ReportDefinition>(base.definition);
  const parsed = fromDsl(base.definition.filter);
  const [model, setModel] = useState<FilterModel>(parsed ?? { join: 'and', rows: [] });
  const complexFilter = parsed === null;
  const problems = rowProblems(model);
  const [view, setView] = useState<'chart' | 'table'>(
    base.definition.chart === 'table' ? 'table' : 'chart',
  );
  const [drill, setDrill] = useState<Drill | null>(null);
  const [copying, setCopying] = useState(false);

  const definition = useMemo<ReportDefinition>(
    () => ({
      ...draft,
      filter: complexFilter ? base.definition.filter : (toDsl(model) as ReportDefinition['filter']),
    }),
    [draft, model, complexFilter, base.definition.filter],
  );
  // Their newer save (or this view's own) becomes the report on screen; edits are dropped.
  const load = (next: Base) => {
    setBase(next);
    setDraft(next.definition);
    setModel(fromDsl(next.definition.filter) ?? { join: 'and', rows: [] });
    setView(next.definition.chart === 'table' ? 'table' : 'chart');
  };
  const edited = JSON.stringify(definition) !== JSON.stringify(base.definition);
  // A newer save made elsewhere is taken while nothing is edited here; with edits, saving
  // meets it in the conflict dialog.
  if (latest.saved?.version !== base.saved?.version && !edited) load(latest);
  // Back to the report as it was opened: its grouping, filter, measures and chart (BUG-08).
  const reset = () => {
    load(base);
  };
  const toRun = useDebounced(definition, RUN_DELAY_MS);
  const run = useReportRun(toRun, problems.size === 0);
  const result = run.data;
  const words = useReportWords(result);
  // A run the server refused (time limit, queue full) is a notice here; a failure (an outage, a
  // server error) is the app's error toast with its reference, once (D-105).
  const refused = run.error instanceof ApiError && run.error.isRefusal;
  useEffect(() => {
    if (run.error && !refused) reportError(run.error);
  }, [run.error, refused]);

  // Live (rule c): the numbers follow the list they count (REQ-RPT-008 AC2).
  useLiveReportRefresh(result?.list_path ?? null);

  const fields = entity.data?.fields ?? [];
  const offered = fields.filter(
    (f) =>
      (INCIDENT_REPORT_FIELDS as readonly string[]).includes(f.name) ||
      f.name.startsWith('custom.'),
  );
  const filterFields: FilterFieldOption[] = offered
    .filter((f) => !(f.dimension?.reference === 'user'))
    .map((f) => ({
      name: f.name,
      type: fieldType(f.type),
      label: words.field(f.name),
      choices: words.choices(f),
    }));
  const groupable = offered.filter((f) => f.dimension !== null && !f.multiple);
  const isDate = (name: string | undefined) =>
    fields.find((f) => f.name === name)?.dimension?.kind === 'datetime';
  const group = draft.group_by?.[0];
  const second = draft.group_by?.[1];

  const setGroup = (index: 0 | 1, field: string | undefined) => {
    const groups = [...(draft.group_by ?? [])];
    if (field === undefined) groups.splice(index, 1);
    else groups[index] = { field, bucket: isDate(field) ? 'day' : null };
    setDraft({ ...draft, group_by: groups.slice(0, index === 0 && field === undefined ? 0 : 2) });
  };

  const joinParts = useJoinParts();
  const rowTitle = (row: ReportRow) =>
    joinParts((result?.groups ?? []).map((g, i) => words.key(g, row.keys[i])));

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Header base={base} definition={definition} result={result} canRun={problems.size === 0} />
      {base.builtin !== null && edited && (
        // A changed built-in report says so: it is no longer the shipped one (QA WP-035 BUG-08).
        <Alert
          type="info"
          showIcon
          data-testid="report-modified"
          message={t('reports.changed_from', { name: isolate(base.name) })}
          description={t('reports.changed_from_hint')}
          action={
            <Space wrap>
              <Button onClick={reset} data-testid="report-reset">
                {t('reports.reset')}
              </Button>
              <WriteButton
                type="primary"
                disabled={problems.size > 0 || !can('reports.create')}
                onClick={() => {
                  setCopying(true);
                }}
              >
                {t('reports.save_copy')}
              </WriteButton>
            </Space>
          }
        />
      )}
      <Card size="small" title={t('reports.filters')}>
        {complexFilter ? (
          <Alert type="info" showIcon message={t('reports.filter_read_only')} />
        ) : (
          <FilterBuilder
            fields={filterFields}
            value={model}
            onChange={setModel}
            testId="report-filter"
          />
        )}
        {problems.size > 0 && (
          <Typography.Text type="danger" role="alert" data-testid="report-cannot-run">
            {t('reports.fix_filter_to_run')}
          </Typography.Text>
        )}
      </Card>
      <Flex wrap gap={12} align="center">
        <Select
          aria-label={t('reports.group_by')}
          prefix={`${t('reports.group_by')}:`}
          allowClear
          placeholder={t('reports.no_grouping')}
          value={group?.field}
          onChange={(value?: string) => {
            setGroup(0, value);
          }}
          options={groupable.map((f) => ({ value: f.name, label: words.field(f.name) }))}
          style={{ minWidth: 220 }}
          data-testid="report-group"
        />
        {group && isDate(group.field) && (
          <Select
            aria-label={t('reports.bucket')}
            value={group.bucket ?? 'day'}
            onChange={(bucket: DateBucket) => {
              setDraft({
                ...draft,
                group_by: [{ field: group.field, bucket }, ...(draft.group_by ?? []).slice(1)],
              });
            }}
            options={BUCKETS.map((b) => ({ value: b, label: t(`report_bucket.${b}`) }))}
            data-testid="report-bucket"
          />
        )}
        {group && (
          <Select
            aria-label={t('reports.then_by')}
            prefix={`${t('reports.then_by')}:`}
            allowClear
            placeholder={t('reports.no_grouping')}
            value={second?.field}
            onChange={(value?: string) => {
              setGroup(1, value);
            }}
            options={groupable
              .filter((f) => f.name !== group.field && !isDate(f.name))
              .map((f) => ({ value: f.name, label: words.field(f.name) }))}
            style={{ minWidth: 200 }}
            data-testid="report-group-2"
          />
        )}
        <Select
          mode="multiple"
          aria-label={t('reports.measures')}
          maxCount={4}
          value={draft.measures ?? ['count']}
          onChange={(measures: string[]) => {
            setDraft({ ...draft, measures: measures.length > 0 ? measures : ['count'] });
          }}
          options={(entity.data?.measures ?? []).map((m) => ({
            value: m.code,
            label: words.measure(base.definition.entity, m.code).name,
          }))}
          style={{ minWidth: 260 }}
          data-testid="report-measures"
        />
        <Select
          aria-label={t('reports.chart')}
          prefix={`${t('reports.chart')}:`}
          value={draft.chart}
          onChange={(chart: ChartType) => {
            setDraft({ ...draft, chart });
            setView(chart === 'table' ? 'table' : 'chart');
          }}
          options={CHARTS.map((c) => ({ value: c, label: t(`report_chart.${c}`) }))}
          data-testid="report-chart-type"
        />
        {draft.chart !== 'table' && draft.chart !== 'kpi' && (
          <Segmented
            aria-label={t('reports.view')}
            value={view}
            onChange={(value) => {
              setView(value as 'chart' | 'table');
            }}
            options={[
              { value: 'chart', label: t('reports.view_chart') },
              { value: 'table', label: t('reports.view_table') },
            ]}
            data-testid="report-view"
          />
        )}
      </Flex>
      {refused && run.error && (
        <Alert
          type="warning"
          showIcon
          message={describeError(run.error, t).title}
          description={describeError(run.error, t).detail}
          data-testid="report-error"
        />
      )}
      {result && (
        <Card
          size="small"
          title={
            <Space wrap>
              <span>{t('reports.as_of', { time: isolate(dates.format(result.as_of)) })}</span>
              <Typography.Text type="secondary">
                {t('reports.times_in', { zone: isolate(result.time_zone) })}
              </Typography.Text>
            </Space>
          }
          loading={run.isPending}
          data-testid="report-result"
        >
          <Results
            result={result}
            definition={toRun}
            words={words}
            view={view}
            onDrill={(row) => {
              setDrill({
                title: rowTitle(row),
                filter: row.drill,
                count: typeof row.values[0] === 'number' ? row.values[0] : null,
              });
            }}
            onDrillAll={() => {
              setDrill({ title: t('reports.all_records'), filter: result.drill_all, count: null });
            }}
          />
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            {t('reports.scope_note')}
          </Typography.Paragraph>
        </Card>
      )}
      <Flex gap={12} wrap align="center">
        <Actions
          copying={copying}
          onCopying={setCopying}
          base={base}
          latest={latest}
          onLoad={load}
          definition={definition}
          canSave={problems.size === 0 && can('reports.create')}
          onSaved={(id) => void navigate(`/reports/${id}`)}
          onDeleted={() => void navigate('/reports')}
        />
        <ExportButton title={base.name} definition={definition} canRun={problems.size === 0} />
        <ScheduleButton
          reportRef={base.ref}
          title={base.name}
          changed={JSON.stringify(definition) !== JSON.stringify(base.definition)}
        />
        <MyExportsButton />
      </Flex>
      <DrillDrawer
        drill={drill}
        onClose={() => {
          setDrill(null);
        }}
      />
    </Space>
  );
}

function Header({
  base,
  definition,
  result,
  canRun,
}: {
  base: Base;
  definition: ReportDefinition;
  result: ReportResult | undefined;
  canRun: boolean;
}) {
  const t = useLabels();
  const isolate = useIsolate();
  const words = useReportWords(result);
  const star = useStarReport();
  const library = useReportLibrary();
  const starred = library.data?.favourites.includes(base.ref) ?? false;
  const fields = useReportEntity(definition.entity).data?.fields ?? [];
  const list = useListFormat();
  const joinParts = useJoinParts();
  const summary = filterInWords(definition.filter, words, fields, t, list, joinParts);
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Typography.Title level={1} style={{ margin: 0 }} data-testid="report-title">
          {base.name}
        </Typography.Title>
        <Button
          aria-label={t(starred ? 'reports.unstar' : 'reports.star')}
          aria-pressed={starred}
          icon={starred ? <StarFilled /> : <StarOutlined />}
          onClick={() => {
            star.mutate({ ref: base.ref, starred: !starred });
          }}
          data-testid="report-star"
        />
      </Flex>
      {base.description && <Typography.Text type="secondary">{base.description}</Typography.Text>}
      <Descriptions size="small" column={1}>
        <Descriptions.Item label={t('reports.applied_filters')}>
          <span data-testid="report-filter-words">{summary}</span>
        </Descriptions.Item>
        {result && (
          <Descriptions.Item label={t('reports.total')}>
            <span data-testid="report-total">
              {joinParts(
                result.measures.map((m, i) =>
                  t('reports.measure_value', {
                    name: isolate(words.measure(result.entity, m.code).name),
                    value: isolate(words.value(m, result.totals[i])),
                  }),
                ),
              )}
            </span>
          </Descriptions.Item>
        )}
      </Descriptions>
      {!canRun && null}
    </Space>
  );
}

/** The applied filter in words (REQ-RPT-050 AC1): "Priority is one of P1, P2 · Created in the last 30 days". */
function filterInWords(
  filter: unknown,
  words: ReportWords,
  fields: ReportField[],
  t: (key: string, p?: Record<string, string | number>) => string,
  list: (items: readonly string[], kind?: ListKind) => string,
  joinParts: (parts: readonly string[]) => string,
): string {
  const model = fromDsl(filter);
  if (model === null) return t('reports.filter_custom');
  if (model.rows.length === 0) return t('reports.filter_none');
  const parts = model.rows.map((row) => {
    const field = words.field(row.field);
    const op = t(`filter_op.${row.op}`);
    const value = row.value;
    if (row.op === 'last_n_days' || row.op === 'next_n_days') {
      return t('reports.filter_days', { field, days: Number(value) });
    }
    if (value === null) return `${field} ${op}`;
    // Every value by its name: codes by their label, groups, sites and people by name, never an
    // id (rule d); lists joined the UI language's way (QA WP-035 BUG-05).
    const group = fields.find((f) => f.name === row.field)?.dimension ?? {
      field: row.field,
      kind: 'code',
      label_prefix: row.field,
      reference: null,
      bucket: null,
    };
    const name = (v: unknown) =>
      typeof v === 'string' && row.op !== 'between' ? words.key(group, v) : String(v);
    const values = (Array.isArray(value) ? value : [value]).filter((v) => v !== null).map(name);
    const named =
      row.op === 'between'
        ? list(values, 'unit')
        : list(values, row.op === 'in' ? 'disjunction' : 'unit');
    return `${field} ${op} ${named}`;
  });
  return model.join === 'and' ? joinParts(parts) : list(parts, 'disjunction');
}

export function Results({
  result,
  definition,
  words,
  view,
  onDrill,
  onDrillAll,
  chartHeight,
}: {
  result: ReportResult;
  definition: ReportDefinition;
  words: ReportWords;
  view: 'chart' | 'table';
  onDrill: (row: ReportRow) => void;
  onDrillAll: () => void;
  /** Dashboard widgets draw smaller charts than the report viewer. */
  chartHeight?: number;
}) {
  const t = useLabels();
  const catalogue = useIncidentCatalogue();
  const chart = definition.chart;
  const measures = result.measures;
  const first = result.groups[0];
  if (chart === 'kpi' || first === undefined) {
    return (
      <Flex wrap gap={24}>
        {measures.map((m, i) => (
          <Statistic
            key={m.code}
            title={
              <Space size={4}>
                {words.measure(result.entity, m.code).name}
                <Tooltip title={words.measure(result.entity, m.code).help}>
                  <InfoCircleOutlined aria-label={words.measure(result.entity, m.code).help} />
                </Tooltip>
              </Space>
            }
            valueRender={() => (
              <Typography.Link onClick={onDrillAll} data-testid={`report-kpi-${m.code}`}>
                {words.value(m, result.totals[i])}
              </Typography.Link>
            )}
          />
        ))}
      </Flex>
    );
  }
  const categoryOf = (row: ReportRow) => words.key(first, row.keys[0]);
  const table = (
    <Table<ReportRow>
      size="small"
      rowKey={(row) => JSON.stringify(row.keys)}
      dataSource={result.rows}
      pagination={{ pageSize: 50, hideOnSinglePage: true }}
      onRow={(row) => ({
        onClick: () => {
          onDrill(row);
        },
        onKeyDown: (event) => {
          if (event.key === 'Enter') onDrill(row);
        },
        tabIndex: 0,
        style: { cursor: 'pointer' },
      })}
      columns={[
        ...result.groups.map((g, gi) => ({
          key: `k${String(gi)}`,
          title: words.field(g.field),
          render: (_: unknown, row: ReportRow) => words.key(g, row.keys[gi]),
        })),
        ...measures.map((m, mi) => ({
          key: `m${String(mi)}`,
          title: (
            <Tooltip title={words.measure(result.entity, m.code).help}>
              {words.measure(result.entity, m.code).name}
            </Tooltip>
          ),
          align: 'end' as const,
          render: (_: unknown, row: ReportRow) =>
            definition.percent && m.unit === 'count'
              ? percentOf(row.values[mi], result.totals[mi])
              : words.value(m, row.values[mi]),
        })),
      ]}
      summary={() => (
        <Table.Summary.Row>
          {result.groups.map((g, gi) => (
            <Table.Summary.Cell key={g.field} index={gi}>
              {gi === 0 ? t('reports.total') : ''}
            </Table.Summary.Cell>
          ))}
          {measures.map((m, mi) => (
            <Table.Summary.Cell key={m.code} index={result.groups.length + mi} align="end">
              {words.value(m, result.totals[mi])}
            </Table.Summary.Cell>
          ))}
        </Table.Summary.Row>
      )}
      data-testid="report-table"
    />
  );
  if (view === 'table' || chart === 'table') return table;

  const second = result.groups[1];
  const priorityColour = (code: unknown) =>
    first.field === 'priority' && typeof code === 'string'
      ? (catalogue.data?.scales.find((v) => v.scale === 'priority' && v.code === code)?.colour ??
        PRIORITY_COLOURS[code as keyof typeof PRIORITY_COLOURS])
      : undefined;
  let categories: string[];
  let series: { name: string; values: (number | null)[] }[];
  let rowsByCategory: ReportRow[][];
  if (second) {
    // Two groupings: the first along the axis, one series per value of the second.
    const keys = [
      ...new Map(result.rows.map((r) => [JSON.stringify(r.keys[0]), r.keys[0]])).values(),
    ];
    const seconds = [
      ...new Map(result.rows.map((r) => [JSON.stringify(r.keys[1]), r.keys[1]])).values(),
    ];
    categories = keys.map((k) => words.key(first, k));
    rowsByCategory = keys.map((k) =>
      result.rows.filter((r) => JSON.stringify(r.keys[0]) === JSON.stringify(k)),
    );
    series = seconds.map((s) => ({
      name: words.key(second, s),
      values: keys.map((k) => {
        const row = result.rows.find(
          (r) =>
            JSON.stringify(r.keys[0]) === JSON.stringify(k) &&
            JSON.stringify(r.keys[1]) === JSON.stringify(s),
        );
        return row?.values[0] ?? null;
      }),
    }));
  } else {
    categories = result.rows.map(categoryOf);
    rowsByCategory = result.rows.map((r) => [r]);
    series = measures.map((m, mi) => ({
      name: words.measure(result.entity, m.code).name,
      values: result.rows.map((r) => r.values[mi] as number | null),
    }));
  }
  const unit = measures[0]?.unit ?? 'count';
  const option = kitOption({
    type: chart === 'gauge' ? 'gauge' : chart,
    categories,
    series:
      chart === 'gauge'
        ? [{ name: series[0]?.name ?? '', values: [result.totals[0] ?? null] }]
        : series,
    categoryColors: second ? undefined : result.rows.map((r) => priorityColour(r.keys[0])),
    format: (value) => words.value({ unit }, value),
    max: unit === 'percent' ? 100 : undefined,
  });
  const summary = t('reports.chart_summary', {
    count: result.rows.length,
    field: words.field(first.field),
  });
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Chart
        option={option}
        ariaLabel={summary}
        height={chartHeight}
        onSelect={(index) => {
          const rows = rowsByCategory[index];
          if (rows?.length === 1 && rows[0]) onDrill(rows[0]);
        }}
      />
      <details>
        <summary>{t('reports.data_table')}</summary>
        {table}
      </details>
    </Space>
  );
}

function percentOf(value: number | null | undefined, total: number | null | undefined): string {
  if (value === null || value === undefined || !total) return '–';
  return `${((value / total) * 100).toFixed(1)}%`;
}

function Actions({
  copying,
  onCopying,
  base,
  latest,
  onLoad,
  definition,
  canSave,
  onSaved,
  onDeleted,
}: {
  /** The "save as my report" dialog is open (also opened from the "changed" notice). */
  copying: boolean;
  onCopying: (open: boolean) => void;
  /** The report as the view opened it (its version goes with the save). */
  base: Base;
  /** The same report as it is now (live), for the conflict dialog. */
  latest: Base;
  /** Show a saved version (theirs, or this save's), edits dropped. */
  onLoad: (next: Base) => void;
  definition: ReportDefinition;
  canSave: boolean;
  onSaved: (id: string) => void;
  onDeleted: () => void;
}) {
  const t = useLabels();
  const isolate = useIsolate();
  const library = useReportLibrary();
  const create = useCreateReport();
  const update = useUpdateReport(base.saved?.id ?? '');
  const remove = useDeleteReport(base.saved?.id ?? '');
  const [name, setName] = useState(t('reports.copy_of', { name: base.name }));
  const [folder, setFolder] = useState<string>('mine');
  const [key] = useState(() => crypto.randomUUID());
  const changed = JSON.stringify(definition) !== JSON.stringify(base.definition);
  // A save someone else beat (409): who, when and what, in the shared dialog (BUG-05).
  const conflict = useConflict();
  const removeConflict = useConflictRetry();
  // Refusals at the page or dialog that saved; failures as the app's toast (D-105).
  const problem = useFormProblem();
  const copyProblem = useFormProblem();
  const removeIt = (version: number): Promise<void> =>
    remove
      .mutateAsync(version)
      .then(onDeleted)
      .catch((error: unknown) => {
        if (!removeConflict.take(error, (at) => void removeIt(at))) problem.show(error);
      });
  const saveChanges = (version: number) => {
    update.mutate(
      { changes: { definition }, version },
      {
        onSuccess: (report) => {
          onLoad(savedBase(report));
        },
        onError: (error) => {
          if (!conflict.take(error)) problem.show(error);
        },
      },
    );
  };
  const whyNot = canSave ? undefined : t('reports.cannot_save');

  return (
    <Flex gap={12} wrap>
      <Tooltip title={whyNot}>
        <WriteButton
          type={base.saved?.canEdit ? 'default' : 'primary'}
          disabled={!canSave}
          onClick={() => {
            onCopying(true);
          }}
          data-testid="report-save-copy"
        >
          {t('reports.save_copy')}
        </WriteButton>
      </Tooltip>
      {base.saved?.canEdit && (
        <>
          <WriteButton
            type="primary"
            disabled={!canSave || !changed}
            loading={update.isPending}
            onClick={() => {
              saveChanges(base.saved?.version ?? 0);
            }}
            data-testid="report-save"
          >
            {t('reports.save_changes')}
          </WriteButton>
          <WriteButton
            danger
            onClick={() =>
              Modal.confirm({
                title: t('reports.delete_confirm', { name: isolate(base.name) }),
                okText: t('reports.delete'),
                okButtonProps: { danger: true },
                cancelText: t('reports.cancel'),
                onOk: () => removeIt(base.saved?.version ?? 0),
              })
            }
            data-testid="report-delete"
          >
            {t('reports.delete')}
          </WriteButton>
        </>
      )}
      {base.saved !== null && !base.saved.canEdit && (
        <Typography.Text type="secondary">{t('reports.not_editable_hint')}</Typography.Text>
      )}
      <div style={{ flexBasis: '100%' }}>
        <FormProblem problem={problem} />
      </div>
      <ConflictDialog
        {...removeConflict.dialog}
        fieldLabel={(field) => t(DEFINITION_PARTS[field] ?? 'reports.layout')}
      />
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => t(DEFINITION_PARTS[field] ?? 'reports.layout')}
        opened={base.definition}
        latest={latest.definition}
        onReload={() => {
          conflict.clear();
          update.reset();
          onLoad(latest);
        }}
        onKeepMine={() => {
          conflict.clear();
          update.reset();
          saveChanges(conflict.latestVersion ?? latest.saved?.version ?? 0);
        }}
      />
      <Modal
        open={copying}
        title={t('reports.save_copy')}
        okText={t('reports.save')}
        cancelText={t('reports.cancel')}
        okButtonProps={{ disabled: name.trim() === '', loading: create.isPending }}
        onCancel={() => {
          onCopying(false);
          copyProblem.clear();
        }}
        onOk={() => {
          copyProblem.clear();
          create.mutate(
            {
              key,
              body: {
                name: name.trim(),
                folder_id: folder === 'mine' ? null : folder,
                definition,
                copied_from: base.builtin,
              },
            },
            {
              onSuccess: (report) => {
                onSaved(report.id);
              },
              onError: (error) => {
                copyProblem.show(error);
              },
            },
          );
        }}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            aria-label={t('reports.name')}
            count={lengthLimit(200)}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
            data-testid="report-save-name"
          />
          <Select
            aria-label={t('reports.folder')}
            value={folder}
            onChange={setFolder}
            style={{ width: '100%' }}
            options={[
              { value: 'mine', label: t('reports.my_reports_private') },
              ...(library.data?.folders ?? []).map((f) => ({
                value: f.id,
                label: t('reports.shared_folder_named', { name: isolate(f.name) }),
              })),
            ]}
            data-testid="report-save-folder"
          />
          {folder !== 'mine' && (
            <Alert type="info" showIcon message={t('reports.shared_save_hint')} />
          )}
          <FormProblem problem={copyProblem} />
        </Space>
      </Modal>
    </Flex>
  );
}
