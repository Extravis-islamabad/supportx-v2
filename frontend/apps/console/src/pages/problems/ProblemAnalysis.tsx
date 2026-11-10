import { EditOutlined, LockOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Card,
  Flex,
  Skeleton,
  Space,
  Statistic,
  Timeline,
  Typography,
} from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  attachDrafts,
  useProblemEvidence,
  useProblemImpact,
  useSession,
  useUpdateProblem,
  type Problem,
} from '@supportx/api-client';
import { Chart, kitOption } from '@supportx/charts';
import { useListFormat } from '@supportx/labels';
import {
  EmptyText,
  ConflictDialog,
  FormProblem,
  inlineImageIds,
  reportError,
  RichTextField,
  RichTextView,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { personName } from '../incidents/labels';
import { PriorityTag } from '../incidents/tags';

type AnalysisName =
  'root_cause' | 'symptoms' | 'workaround' | 'review_summary' | 'review_lessons' | 'review_actions';

/**
 * One analysis field (REQ-PRB-030): read, or edited in place with its own save, so each change
 * is one history entry. Editing needs "edit analysis"; the server refuses it otherwise (403).
 * A root cause the reader may not see shows as locked, never as empty (D-140 Q7).
 */
function AnalysisField({
  item,
  name,
  canEdit,
  reload,
}: {
  item: Problem;
  name: AnalysisName;
  canEdit: boolean;
  reload: () => Promise<unknown>;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const me = useSession().data?.user.id ?? null;
  const { format } = useDateTime();
  const update = useUpdateProblem(item.id);
  const problem = useFormProblem();
  const value = item[name] ?? null;
  const [editing, setEditing] = useState(false);
  const [html, setHtml] = useState(value ?? '');
  const [conflict, setConflict] = useState<unknown>(null);
  const hidden = name === 'root_cause' && item.root_cause_hidden;
  const testId = `prb-${name.replace('_', '-')}`;
  const save = (version: number) => {
    problem.clear();
    update.mutate(
      { changes: { [name]: html }, version },
      {
        onSuccess: () => {
          attachDrafts('work_item', item.id, inlineImageIds(html)).catch(reportError);
          void message.success(t('problems.analysis.saved'));
          setEditing(false);
        },
        onError: (failure) => {
          if (failure instanceof ApiError && failure.code === 'version_conflict')
            setConflict(failure);
          else problem.show(failure);
        },
      },
    );
  };
  const title = t(`work_item.field.${name}`);
  const last = (item.analysis_changes ?? []).find((c) => c.field === name);
  if (hidden) {
    return (
      <Card size="small" title={title} data-testid={testId}>
        <Alert
          type="info"
          showIcon
          icon={<LockOutlined />}
          message={t('problems.analysis.root_cause_hidden')}
          data-testid="prb-root-cause-hidden"
        />
      </Card>
    );
  }
  return (
    <Card
      size="small"
      title={title}
      data-testid={testId}
      extra={
        canEdit && !editing ? (
          <WriteButton
            size="small"
            icon={<EditOutlined />}
            aria-label={t('problems.analysis.edit', { field: title })}
            data-testid={`${testId}-edit`}
            onClick={() => {
              setHtml(value ?? '');
              setEditing(true);
            }}
          >
            {t('actions.edit')}
          </WriteButton>
        ) : undefined
      }
    >
      {editing ? (
        <Space direction="vertical" style={{ width: '100%' }}>
          <RichTextField
            label={title}
            value={html}
            onChange={setHtml}
            testId={`${testId}-editor`}
            imageOwnerId={me ?? undefined}
          />
          <FormProblem problem={problem} />
          <Space>
            <WriteButton
              type="primary"
              loading={update.isPending}
              data-testid={`${testId}-save`}
              onClick={() => {
                save(item.version);
              }}
            >
              {t('actions.save')}
            </WriteButton>
            <Button
              onClick={() => {
                setEditing(false);
                problem.clear();
              }}
            >
              {t('actions.cancel')}
            </Button>
          </Space>
        </Space>
      ) : value === null ? (
        <Typography.Text type="secondary">{t('problems.analysis.empty')}</Typography.Text>
      ) : (
        <RichTextView html={value} testId={`${testId}-view`} />
      )}
      {last !== undefined && !editing && (
        <Typography.Text
          type="secondary"
          style={{ display: 'block', marginTop: 8 }}
          data-testid={`${testId}-changed`}
        >
          {last.changed_by === null
            ? t('problems.analysis.changed_system', { date: format(last.changed_at) })
            : t('problems.analysis.changed', {
                name: personName(item.people, last.changed_by),
                date: format(last.changed_at),
              })}
        </Typography.Text>
      )}
      <ConflictDialog
        open={conflict !== null}
        error={conflict}
        fieldLabel={(field) => t(`work_item.field.${field}`)}
        onReload={() => {
          setConflict(null);
          void reload().then(() => {
            setEditing(false);
          });
        }}
        onKeepMine={() => {
          setConflict(null);
          void reload().then((fresh) => {
            if (typeof fresh === 'object' && fresh !== null && 'version' in fresh) {
              save((fresh as Problem).version);
            }
          });
        }}
      />
    </Card>
  );
}

/** Figures from the caused incidents the reader may see (REQ-PRB-033). */
function ImpactFigures({ id }: { id: string }) {
  const t = useLabel();
  const impact = useProblemImpact(id);
  const { formatDay } = useDateTime();
  if (impact.data === undefined) return <Skeleton active paragraph={{ rows: 1 }} />;
  const d = impact.data;
  const hours = Math.round((d.minutes / 60) * 10) / 10;
  const openHours = Math.round((d.open_seconds / 3600) * 10) / 10;
  const weeks = d.weekly.map((w) => formatDay(w.week_start.slice(0, 10)));
  const counts = d.weekly.map((w) => w.count);
  return (
    <Card size="small" title={t('problems.impact.title')} data-testid="prb-impact">
      <Flex vertical gap={12}>
        <Flex gap={24} wrap>
          <Statistic
            title={t('problems.impact.incidents')}
            value={d.incidents}
            data-testid="prb-impact-incidents"
          />
          <Statistic title={t('problems.impact.open')} value={d.open_incidents} />
          <Statistic title={t('problems.impact.people')} value={d.people} />
          <Statistic title={t('problems.impact.sites')} value={d.by_site.length} />
          <Statistic
            title={t('problems.impact.open_hours')}
            value={openHours}
            data-testid="prb-impact-open-hours"
          />
          <Statistic
            title={t('problems.impact.hours')}
            value={hours}
            data-testid="prb-impact-hours"
          />
        </Flex>
        {d.by_priority.length > 0 && (
          <Flex gap={8} wrap align="center">
            {d.by_priority.map((p) => (
              <Space key={p.priority} size={4}>
                <PriorityTag priority={p.priority} source="matrix" />
                <span>{t('problems.impact.count', { count: p.count })}</span>
              </Space>
            ))}
          </Flex>
        )}
        {d.incidents > 0 && (
          <div data-testid="prb-impact-trend">
            <Typography.Text type="secondary">{t('problems.impact.trend')}</Typography.Text>
            <Chart
              height={140}
              ariaLabel={t('problems.impact.trend_summary', {
                weeks: weeks.length,
                total: counts.reduce((a, b) => a + b, 0),
              })}
              option={kitOption({
                type: 'bar',
                categories: weeks,
                series: [{ name: t('problems.impact.incidents'), values: counts }],
              })}
            />
          </div>
        )}
        {d.partial && (
          <Typography.Text type="secondary" data-testid="prb-impact-partial">
            {t('problems.impact.partial')}
          </Typography.Text>
        )}
      </Flex>
    </Card>
  );
}

/** The analysis tab: impact, root cause, symptoms, workaround and the review (WP-044b D8, D10, D11). */
export function ProblemAnalysis({
  item,
  reload,
}: {
  item: Problem;
  reload: () => Promise<unknown>;
}) {
  const t = useLabel();
  const may = (op: string) => item.operations.find((o) => o.action === op)?.allowed === true;
  const canEdit = may('edit_analysis');
  return (
    <Flex vertical gap={16} data-testid="prb-analysis">
      <ImpactFigures id={item.id} />
      <AnalysisField item={item} name="root_cause" canEdit={canEdit} reload={reload} />
      <AnalysisField item={item} name="symptoms" canEdit={canEdit} reload={reload} />
      {/* The solution (REQ-PRB-034): its own right; incident technicians see it (D-140 Q7). */}
      <AnalysisField item={item} name="workaround" canEdit={may('edit_solution')} reload={reload} />
      {/* The review (REQ-PRB-053): needed before closing major and listed-priority problems. */}
      <Flex vertical gap={8} data-testid="prb-review">
        <Typography.Title level={2} style={{ fontSize: 16, margin: 0 }}>
          {t('problems.review.title')}
        </Typography.Title>
        {item.review_required && (item.review_summary ?? '') === '' && (
          <Alert
            type="warning"
            showIcon
            message={t('problems.review.required')}
            data-testid="prb-review-required"
          />
        )}
        <AnalysisField item={item} name="review_summary" canEdit={canEdit} reload={reload} />
        <AnalysisField item={item} name="review_lessons" canEdit={canEdit} reload={reload} />
        <AnalysisField item={item} name="review_actions" canEdit={canEdit} reload={reload} />
      </Flex>
    </Flex>
  );
}

/**
 * The evidence panel (REQ-PRB-032): the caused incidents by when they were reported. Sources
 * that are not there yet (changes, releases, other problems on the same items) are named, so
 * the panel never looks complete when it is not. Records the reader may not see are left out.
 */
export function ProblemEvidence({ id }: { id: string }) {
  const t = useLabel();
  const { format } = useDateTime();
  const list = useListFormat();
  const evidence = useProblemEvidence(id);
  if (evidence.data === undefined) return <Skeleton active />;
  const d = evidence.data;
  return (
    <Flex vertical gap={16} data-testid="prb-evidence">
      {d.pending_sources.length > 0 && (
        <Alert
          type="info"
          showIcon
          data-testid="prb-evidence-pending"
          message={t('problems.evidence.pending', {
            sources: list(
              d.pending_sources.map((s) => t(`problem_evidence_source.${s}`)),
              'conjunction',
            ),
          })}
        />
      )}
      {d.incidents.length === 0 ? (
        <EmptyText>{t('problems.evidence.none')}</EmptyText>
      ) : (
        <Timeline
          items={d.incidents.map((i) => ({
            key: i.id,
            color: i.resolved_at === null ? 'red' : 'green',
            children: (
              <Flex vertical gap={2} data-testid={`prb-evidence-${i.display_id}`}>
                <Typography.Text type="secondary">{format(i.reported_at)}</Typography.Text>
                <Link to={`/incidents/${i.id}`}>
                  <strong dir="ltr">{i.display_id}</strong> <bdi dir="auto">{i.subject}</bdi>
                </Link>
                <Space size={4}>
                  <PriorityTag priority={i.priority} source="matrix" />
                  {i.resolved_at !== null && (
                    <Typography.Text type="secondary">
                      {t('problems.evidence.resolved', { date: format(i.resolved_at) })}
                    </Typography.Text>
                  )}
                </Space>
              </Flex>
            ),
          }))}
        />
      )}
      {d.left_out && (
        <Typography.Text type="secondary" data-testid="prb-evidence-left-out">
          {t('problems.evidence.left_out')}
        </Typography.Text>
      )}
    </Flex>
  );
}
