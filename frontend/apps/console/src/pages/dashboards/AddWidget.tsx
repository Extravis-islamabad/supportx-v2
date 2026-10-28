import { PlusOutlined } from '@ant-design/icons';
import { Button, Form, Input, Modal, Radio, Select, Switch } from 'antd';
import { useMemo, useState } from 'react';

import {
  useReportEntity,
  useReportLibrary,
  useSession,
  type ChartType,
  type DashboardWidget,
  type ReportDefinition,
  type WidgetCatalogueEntry,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { lengthLimit } from '@supportx/ui';

import { INCIDENT_REPORT_FIELDS, useReportWords } from '../reports/names';
import { RecordsWidget } from './RecordsWidget';
import { WidgetCataloguePicker } from './WidgetCatalogue';
import { widgetDefinition } from './widgetDefinition';
import { Widget } from './Widget';

const CHARTS: ChartType[] = ['kpi', 'bar', 'stacked_bar', 'line', 'area', 'doughnut', 'table'];

/**
 * "Add widget" (REQ-DSH-007 AC1, REQ-DSH-009): one action, the searchable widget catalogue
 * (D-114), a search over every report, or a quick chart (grouping, measure, chart type, number
 * or percent), with a live preview of real data before adding (REQ-DSH-007 AC2).
 */
export function AddWidget({
  taken,
  below,
  onAdd,
}: {
  taken: string[];
  /** The first free row: a new widget goes under the others. */
  below: number;
  onAdd: (widget: DashboardWidget) => void;
}) {
  const t = useLabels();
  const session = useSession().data;
  const library = useReportLibrary();
  const entity = useReportEntity('incident');
  const words = useReportWords();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<'catalogue' | 'report' | 'quick'>('catalogue');
  const [entry, setEntry] = useState<WidgetCatalogueEntry>();
  const [reportRef, setReportRef] = useState<string>();
  const [title, setTitle] = useState('');
  const [group, setGroup] = useState<string>();
  const [measure, setMeasure] = useState('count');
  const [chart, setChart] = useState<ChartType>('bar');
  const [percent, setPercent] = useState(false);

  const fields = (entity.data?.fields ?? []).filter(
    (f) =>
      f.dimension !== null &&
      !f.multiple &&
      ((INCIDENT_REPORT_FIELDS as readonly string[]).includes(f.name) ||
        f.name.startsWith('custom.')),
  );
  const isDate = (name?: string) =>
    fields.find((f) => f.name === name)?.dimension?.kind === 'datetime';
  const reports = [
    ...(library.data?.builtin ?? []).map((r) => ({
      value: `builtin:${r.code}`,
      label: t(`report.${r.code}`),
    })),
    ...(library.data?.reports ?? []).map((r) => ({ value: r.id, label: r.name })),
  ];
  const id = (() => {
    let n = taken.length + 1;
    while (taken.includes(`w${String(n)}`)) n += 1;
    return `w${String(n)}`;
  })();
  const kpi = source === 'quick' && (chart === 'kpi' || group === undefined);
  const widget: DashboardWidget | null = useMemo(() => {
    const place = kpi ? { x: 0, y: below, w: 3, h: 2 } : { x: 0, y: below, w: 6, h: 4 };
    if (source === 'catalogue') {
      if (!entry) return null;
      const [w, h] = [entry.widget.place.w, entry.widget.place.h];
      const named = title.trim();
      return {
        ...entry.widget,
        id,
        ...(named ? { title: named, title_key: null } : {}),
        place: { x: 0, y: below, w, h },
      };
    }
    if (source === 'report') {
      if (!reportRef) return null;
      const name = reports.find((r) => r.value === reportRef)?.label ?? '';
      return { id, title: title.trim() || name, report_ref: reportRef, place };
    }
    const report: ReportDefinition = {
      schema_version: 1,
      entity: 'incident',
      order: 'key',
      group_by: group && !kpi ? [{ field: group, bucket: isDate(group) ? 'day' : null }] : [],
      measures: [measure],
      chart: kpi ? 'kpi' : chart,
      percent,
    };
    return {
      id,
      title: title.trim() || (group ? words.field(group) : words.measure('incident', measure).name),
      report,
      place,
    };
    // `reports` and `words` change identity each render; their content is what matters here.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
  }, [source, entry, reportRef, title, group, measure, chart, percent, below, id, kpi]);
  const preview = widget
    ? widgetDefinition(widget, {
        userId: session?.user.id ?? '',
        filters: {},
        builtin: library.data?.builtin,
      })
    : null;

  return (
    <>
      <Button
        icon={<PlusOutlined />}
        onClick={() => {
          setOpen(true);
        }}
        data-testid="dashboard-add-widget"
      >
        {t('dashboards.add_widget')}
      </Button>
      <Modal
        open={open}
        title={t('dashboards.add_widget')}
        width="min(900px, 96vw)"
        okText={t('dashboards.add')}
        cancelText={t('reports.cancel')}
        okButtonProps={{ disabled: widget === null, 'data-testid': 'dashboard-add-confirm' }}
        onCancel={() => {
          setOpen(false);
        }}
        onOk={() => {
          if (widget) onAdd(widget);
          setOpen(false);
          setTitle('');
        }}
      >
        <Form layout="vertical">
          <Form.Item>
            <Radio.Group
              value={source}
              onChange={(event) => {
                setSource(event.target.value as 'catalogue' | 'report' | 'quick');
              }}
              options={[
                { value: 'catalogue', label: t('dashboards.source_catalogue') },
                { value: 'quick', label: t('dashboards.quick_chart') },
                { value: 'report', label: t('dashboards.from_report') },
              ]}
              data-testid="dashboard-add-source"
            />
          </Form.Item>
          {source === 'catalogue' ? (
            <Form.Item>
              <WidgetCataloguePicker value={entry?.code} onChange={setEntry} />
            </Form.Item>
          ) : source === 'report' ? (
            <Form.Item label={t('dashboards.report')}>
              <Select
                showSearch
                optionFilterProp="label"
                value={reportRef}
                onChange={setReportRef}
                options={reports}
                placeholder={t('reports.search')}
                data-testid="dashboard-add-report"
              />
            </Form.Item>
          ) : (
            <>
              <Form.Item label={t('reports.group_by')}>
                <Select
                  allowClear
                  value={group}
                  onChange={setGroup}
                  placeholder={t('reports.no_grouping')}
                  options={fields.map((f) => ({ value: f.name, label: words.field(f.name) }))}
                  data-testid="dashboard-add-group"
                />
              </Form.Item>
              <Form.Item label={t('reports.measures')}>
                <Select
                  value={measure}
                  onChange={setMeasure}
                  options={(entity.data?.measures ?? []).map((m) => ({
                    value: m.code,
                    label: words.measure('incident', m.code).name,
                  }))}
                  data-testid="dashboard-add-measure"
                />
              </Form.Item>
              <Form.Item label={t('reports.chart')}>
                <Select
                  value={chart}
                  onChange={setChart}
                  options={CHARTS.map((c) => ({ value: c, label: t(`report_chart.${c}`) }))}
                  data-testid="dashboard-add-chart"
                />
              </Form.Item>
              <Form.Item label={t('dashboards.percent')}>
                <Switch checked={percent} onChange={setPercent} />
              </Form.Item>
            </>
          )}
          <Form.Item label={t('dashboards.widget_title')}>
            <Input
              value={title}
              count={lengthLimit(120)}
              onChange={(event) => {
                setTitle(event.target.value);
              }}
              data-testid="dashboard-add-title"
            />
          </Form.Item>
        </Form>
        {widget && (
          // A preview with real data before it is added (REQ-DSH-007 AC2).
          <div style={{ height: widget.place.h * 72 + 40 }} data-testid="dashboard-add-preview">
            {widget.records ? (
              <RecordsWidget
                widget={widget}
                userId={session?.user.id ?? ''}
                filters={{}}
                onDrill={() => undefined}
              />
            ) : (
              <Widget
                widget={widget}
                definition={preview}
                unfiltered={[]}
                onDrill={() => undefined}
              />
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
