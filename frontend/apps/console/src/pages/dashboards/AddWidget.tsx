import { PlusOutlined } from '@ant-design/icons';
import { Button, Form, Input, Modal, Radio, Select, Switch } from 'antd';
import { useId, useMemo, useState } from 'react';

import {
  useReportEntity,
  useReportLibrary,
  useSession,
  type ChartType,
  type DashboardWidget,
  type ReportDefinition,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { lengthLimit } from '@supportx/ui';

import { fieldLabelKey, INCIDENT_REPORT_FIELDS, useReportWords } from '../reports/names';
import { widgetDefinition } from './widgetDefinition';
import { Widget } from './Widget';

const CHARTS: ChartType[] = ['kpi', 'bar', 'stacked_bar', 'line', 'area', 'doughnut', 'table'];

/**
 * "Add widget" (REQ-DSH-007 AC1, REQ-DSH-009): one action, a search over every report, or a
 * quick chart (grouping, measure, chart type, number or percent), with a live preview of real
 * data before adding (REQ-DSH-007 AC2).
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
  // Each control is named by its label (QA WP-036 BUG-04): the label points at the control's id.
  const ids = useId();
  const [source, setSource] = useState<'report' | 'quick'>('quick');
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
    // A title typed by the user is theirs; otherwise a shipped name is kept as its label key, so
    // every viewer reads it in their own language (QA WP-036 BUG-03).
    const typed = title.trim();
    if (source === 'report') {
      if (!reportRef) return null;
      if (typed) return { id, title: typed, report_ref: reportRef, place };
      if (reportRef.startsWith('builtin:')) {
        const code = reportRef.slice('builtin:'.length);
        return { id, title_key: `report.${code}`, report_ref: reportRef, place };
      }
      // A saved report's name is its owner's own words.
      const name = reports.find((r) => r.value === reportRef)?.label ?? '';
      return { id, title: name, report_ref: reportRef, place };
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
    if (typed) return { id, title: typed, report, place };
    // A custom field's name is the admin's own words; shipped fields and measures have labels.
    if (group?.startsWith('custom.')) return { id, title: words.field(group), report, place };
    return {
      id,
      title_key: group ? fieldLabelKey(group) : `measure.incident.${measure}`,
      report,
      place,
    };
    // `reports` and `words` change identity each render; their content is what matters here.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
  }, [source, reportRef, title, group, measure, chart, percent, below, id, kpi]);
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
                setSource(event.target.value as 'report' | 'quick');
              }}
              options={[
                { value: 'quick', label: t('dashboards.quick_chart') },
                { value: 'report', label: t('dashboards.from_report') },
              ]}
              data-testid="dashboard-add-source"
            />
          </Form.Item>
          {source === 'report' ? (
            <Form.Item label={t('dashboards.report')} htmlFor={`${ids}-report`}>
              <Select
                id={`${ids}-report`}
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
              <Form.Item label={t('reports.group_by')} htmlFor={`${ids}-group`}>
                <Select
                  id={`${ids}-group`}
                  allowClear
                  value={group}
                  onChange={setGroup}
                  placeholder={t('reports.no_grouping')}
                  options={fields.map((f) => ({ value: f.name, label: words.field(f.name) }))}
                  data-testid="dashboard-add-group"
                />
              </Form.Item>
              <Form.Item label={t('reports.measures')} htmlFor={`${ids}-measure`}>
                <Select
                  id={`${ids}-measure`}
                  value={measure}
                  onChange={setMeasure}
                  options={(entity.data?.measures ?? []).map((m) => ({
                    value: m.code,
                    label: words.measure('incident', m.code).name,
                  }))}
                  data-testid="dashboard-add-measure"
                />
              </Form.Item>
              <Form.Item label={t('reports.chart')} htmlFor={`${ids}-chart`}>
                <Select
                  id={`${ids}-chart`}
                  value={chart}
                  onChange={setChart}
                  options={CHARTS.map((c) => ({ value: c, label: t(`report_chart.${c}`) }))}
                  data-testid="dashboard-add-chart"
                />
              </Form.Item>
              <Form.Item label={t('dashboards.percent')} htmlFor={`${ids}-percent`}>
                <Switch id={`${ids}-percent`} checked={percent} onChange={setPercent} />
              </Form.Item>
            </>
          )}
          <Form.Item label={t('dashboards.widget_title')} htmlFor={`${ids}-title`}>
            <Input
              id={`${ids}-title`}
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
            <Widget
              widget={widget}
              definition={preview}
              unfiltered={[]}
              onDrill={() => undefined}
            />
          </div>
        )}
      </Modal>
    </>
  );
}
