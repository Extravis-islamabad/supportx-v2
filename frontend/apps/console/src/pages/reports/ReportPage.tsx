import { InfoCircleOutlined, StarFilled, StarOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
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
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  queryKeys,
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
  type ReportResult,
  type ReportRow,
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
import { useLabels } from '@supportx/labels';
import { refreshList, useListChannel } from '@supportx/realtime';
import {
  describeError,
  lengthLimit,
  NoAccess,
  useAccess,
  useDateTime,
  WriteButton,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { PRIORITY_COLOURS } from '../incidents/priorityColours';
import { DrillDrawer, type Drill } from './DrillDrawer';
import { ExportButton, MyExportsButton } from './exports';
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
// Live: list signals can arrive in bursts (bulk edits); a report refreshes at most once a second.
const LIVE_REFRESH_MS = 1_000;

interface Base {
  ref: string;
  name: string;
  description: string;
  definition: ReportDefinition;
  builtin: string | null;
  saved: { id: string; version: number; canEdit: boolean } | null;
}

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
    return report
      ? {
          ref: report.id,
          name: report.name,
          description: report.description ?? '',
          definition: report.definition,
          builtin: null,
          saved: { id: report.id, version: report.version, canEdit: report.can_edit },
        }
      : null;
  }, [code, library.data, saved.data, t]);

  if (!allowed) return <NoAccess titleKey="nav.reports" />;
  const loading = code !== undefined ? library.isPending : saved.isPending;
  if (base === null) {
    return loading ? null : <Result status="404" title={t('errors.report_not_found')} />;
  }
  // Keyed by report and version: another report, or a newer save, starts from its definition.
  return <ReportView key={`${base.ref}:${String(base.saved?.version ?? 0)}`} base={base} />;
}

function fieldType(type: string): FilterValueType {
  return (
    (['string', 'enum', 'uuid', 'datetime', 'integer', 'boolean', 'decimal', 'date'] as const).find(
      (known) => known === type,
    ) ?? 'string'
  );
}

function ReportView({ base }: { base: Base }) {
  const t = useLabels();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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

  const definition = useMemo<ReportDefinition>(
    () => ({
      ...draft,
      filter: complexFilter ? base.definition.filter : (toDsl(model) as ReportDefinition['filter']),
    }),
    [draft, model, complexFilter, base.definition.filter],
  );
  const toRun = useDebounced(definition, RUN_DELAY_MS);
  const run = useReportRun(toRun, problems.size === 0);
  const result = run.data;
  const words = useReportWords(result);

  // Live (rule c): the numbers follow the list they count (REQ-RPT-008 AC2).
  const last = useRef(0);
  const pending = useRef<number | null>(null);
  useListChannel(result?.list_path ?? null, () => {
    const wait = Math.max(0, last.current + LIVE_REFRESH_MS - Date.now());
    if (pending.current !== null) return;
    pending.current = window.setTimeout(() => {
      pending.current = null;
      last.current = Date.now();
      refreshList(queryClient, queryKeys.reports.runs);
    }, wait);
  });
  useEffect(
    () => () => {
      if (pending.current !== null) window.clearTimeout(pending.current);
    },
    [],
  );

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

  const rowTitle = (row: ReportRow) =>
    (result?.groups ?? []).map((g, i) => words.key(g, row.keys[i])).join(' · ');

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Header base={base} definition={definition} result={result} canRun={problems.size === 0} />
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
      {run.error && (
        <Alert
          type="error"
          showIcon
          message={describeError(run.error, t).title}
          data-testid="report-error"
        />
      )}
      {result && (
        <Card
          size="small"
          title={
            <Space wrap>
              <span>{t('reports.as_of', { time: dates.format(result.as_of) })}</span>
              <Typography.Text type="secondary">
                {t('reports.times_in', { zone: result.time_zone })}
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
          base={base}
          definition={definition}
          canSave={problems.size === 0 && can('reports.create')}
          onSaved={(id) => void navigate(`/reports/${id}`)}
          onDeleted={() => void navigate('/reports')}
        />
        <ExportButton title={base.name} definition={definition} canRun={problems.size === 0} />
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
  const words = useReportWords(result);
  const star = useStarReport();
  const library = useReportLibrary();
  const starred = library.data?.favourites.includes(base.ref) ?? false;
  const summary = filterInWords(definition.filter, words, t);
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
              {result.measures
                .map(
                  (m, i) =>
                    `${words.measure(result.entity, m.code).name}: ${words.value(m, result.totals[i])}`,
                )
                .join(' · ')}
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
  t: (key: string, p?: Record<string, string | number>) => string,
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
    const shown = Array.isArray(value) ? value.filter((v) => v !== null).join(', ') : String(value);
    const group = {
      field: row.field,
      kind: 'code',
      label_prefix: row.field,
      reference: null,
      bucket: null,
    } as const;
    const named =
      Array.isArray(value) && row.op !== 'between'
        ? value
            .map((v) =>
              typeof v === 'string' && !/^[0-9a-f-]{36}$/.test(v) ? words.key(group, v) : v,
            )
            .join(', ')
        : shown;
    return `${field} ${op} ${named}`;
  });
  return parts.join(model.join === 'and' ? ' · ' : ` ${t('reports.or')} `);
}

function Results({
  result,
  definition,
  words,
  view,
  onDrill,
  onDrillAll,
}: {
  result: ReportResult;
  definition: ReportDefinition;
  words: ReportWords;
  view: 'chart' | 'table';
  onDrill: (row: ReportRow) => void;
  onDrillAll: () => void;
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
  base,
  definition,
  canSave,
  onSaved,
  onDeleted,
}: {
  base: Base;
  definition: ReportDefinition;
  canSave: boolean;
  onSaved: (id: string) => void;
  onDeleted: () => void;
}) {
  const t = useLabels();
  const library = useReportLibrary();
  const create = useCreateReport();
  const update = useUpdateReport(base.saved?.id ?? '');
  const remove = useDeleteReport(base.saved?.id ?? '');
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(t('reports.copy_of', { name: base.name }));
  const [folder, setFolder] = useState<string>('mine');
  const [key] = useState(() => crypto.randomUUID());
  const changed = JSON.stringify(definition) !== JSON.stringify(base.definition);
  const whyNot = canSave ? undefined : t('reports.cannot_save');

  return (
    <Flex gap={12} wrap>
      <Tooltip title={whyNot}>
        <WriteButton
          type={base.saved?.canEdit ? 'default' : 'primary'}
          disabled={!canSave}
          onClick={() => {
            setOpen(true);
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
              update.mutate({ changes: { definition }, version: base.saved?.version ?? 0 });
            }}
            data-testid="report-save"
          >
            {t('reports.save_changes')}
          </WriteButton>
          <WriteButton
            danger
            onClick={() =>
              Modal.confirm({
                title: t('reports.delete_confirm', { name: base.name }),
                okText: t('reports.delete'),
                okButtonProps: { danger: true },
                cancelText: t('reports.cancel'),
                onOk: () => remove.mutateAsync(base.saved?.version ?? 0).then(onDeleted),
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
      {update.error && (
        <Typography.Text type="danger" role="alert">
          {describeError(update.error, t).title}
        </Typography.Text>
      )}
      <Modal
        open={open}
        title={t('reports.save_copy')}
        okText={t('reports.save')}
        cancelText={t('reports.cancel')}
        okButtonProps={{ disabled: name.trim() === '', loading: create.isPending }}
        onCancel={() => {
          setOpen(false);
        }}
        onOk={() => {
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
                label: t('reports.shared_folder_named', { name: f.name }),
              })),
            ]}
            data-testid="report-save-folder"
          />
          {folder !== 'mine' && (
            <Alert type="info" showIcon message={t('reports.shared_save_hint')} />
          )}
          {create.error && (
            <Typography.Text type="danger" role="alert">
              {describeError(create.error, t).title}
            </Typography.Text>
          )}
        </Space>
      </Modal>
    </Flex>
  );
}
