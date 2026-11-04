import { BugOutlined, CloseOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Empty, Flex, List, Result, Select, Skeleton, Steps, Typography } from 'antd';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import {
  problemKeys,
  useCopyProblem,
  useInvestigatorChange,
  useInvestigators,
  useProblem,
  useProblemAction,
  useProblemCatalogue,
  useProblemLinks,
  useProblemPeople,
  useSession,
  type Problem,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import {
  ActionBar,
  PropertiesPanel,
  PropertyRow,
  RecordHeader,
  RecordPage,
  RichTextView,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
  type RecordAction,
} from '@supportx/ui';

import { labelled, personName } from '../incidents/labels';
import { useStatusActions } from '../incidents/StatusActions';
import { PriorityTag, StatusTag } from '../incidents/tags';
import { useDebounced } from '../../useDebounced';

// The guided analysis steps in order (REQ-PRB-025, Appendix A); closed ends them.
const GUIDED = [
  'gathering_facts',
  'why_analysis',
  'cause_confirmed',
  'fix_planned',
  'fix_verified',
  'in_review',
  'closed',
] as const;

/** Where a guided problem stands: on hold shows the step it was paused at. */
function GuidedSteps({ record }: { record: Problem }) {
  const t = useLabel();
  const at = record.status === 'on_hold' ? (record.status_before_pause ?? '') : record.status;
  const index = GUIDED.indexOf(at as (typeof GUIDED)[number]);
  return (
    <Steps
      size="small"
      responsive
      data-testid="prb-guided-steps"
      current={Math.max(index, 0)}
      status={
        record.status === 'canceled' ? 'error' : record.status === 'on_hold' ? 'wait' : 'process'
      }
      items={GUIDED.map((step, position) => ({
        title: t(`work_item_status.${step}`),
        status: index < 0 ? 'wait' : position < index ? 'finish' : undefined,
      }))}
    />
  );
}

/** The incidents this problem causes (caused by links), each opening the incident. */
function CausedIncidents({ id }: { id: string }) {
  const t = useLabel();
  const links = useProblemLinks(id);
  const rows = (links.data ?? []).filter((l) => l.relation === 'causes');
  if (links.isLoading) return <Skeleton active paragraph={{ rows: 2 }} />;
  if (rows.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('problems.no_incidents')} />;
  }
  return (
    <List
      size="small"
      dataSource={rows}
      data-testid="prb-incidents"
      renderItem={(link) => (
        <List.Item>
          {link.other_id === null ? (
            t('problems.hidden_incident')
          ) : (
            <Link to={`/incidents/${link.other_id}`}>
              <strong dir="ltr">{link.other_display_id}</strong>{' '}
              <bdi dir="auto">{link.other_subject}</bdi>
            </Link>
          )}
        </List.Item>
      )}
    />
  );
}

/** Investigators (REQ-PRB-029, ADR-040): technicians who work it besides the owner. */
function Investigators({ id, canEdit, me }: { id: string; canEdit: boolean; me: string }) {
  const t = useLabel();
  const found = useInvestigators(id);
  const change = useInvestigatorChange(id);
  const [search, setSearch] = useState('');
  const people = useProblemPeople(canEdit ? id : '', useDebounced(search, 300));
  const ids = found.data?.user_ids ?? [];
  const names = found.data?.people ?? {};
  const run = (userId: string, add: boolean) => {
    change.mutate({ userId, add }, { onError: reportError });
  };
  return (
    <Flex vertical gap={8} data-testid="prb-investigators">
      {ids.length === 0 && (
        <Typography.Text type="secondary">{t('problems.investigators.none')}</Typography.Text>
      )}
      {ids.map((userId) => (
        <Flex key={userId} justify="space-between" align="center">
          <bdi dir="auto">{names[userId]?.display_name ?? ''}</bdi>
          {(canEdit || userId === me) && (
            <Button
              size="small"
              type="text"
              icon={<CloseOutlined />}
              aria-label={t('problems.investigators.remove', {
                name: names[userId]?.display_name ?? '',
              })}
              onClick={() => {
                run(userId, false);
              }}
              data-testid={`prb-investigator-remove-${userId}`}
            />
          )}
        </Flex>
      ))}
      {canEdit && (
        <Select
          showSearch
          filterOption={false}
          value={null}
          placeholder={t('problems.investigators.add')}
          aria-label={t('problems.investigators.add')}
          onSearch={setSearch}
          onChange={(userId: string) => {
            run(userId, true);
          }}
          loading={people.isFetching}
          options={(people.data ?? [])
            .filter((p) => !ids.includes(p.id))
            .map((p) => ({ value: p.id, label: p.display_name }))}
          data-testid="prb-investigator-add"
        />
      )}
    </Flex>
  );
}

/**
 * One problem (WP-044a s5): the header with its status moves (the incidents' status bar and
 * dialogs, run on the problem), the guided steps on the major problem template's life cycle,
 * the description, the incidents it causes and its investigators; copy makes a new problem.
 * Live on the record channel. Tabs for analysis, tasks and the conversation come with WP-044b/c.
 */
export function ProblemPage() {
  const t = useLabel();
  const { id = '' } = useParams();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const record = useProblem(id);
  useRecordChannel('wi', id === '' ? undefined : id, () => {
    void queryClient.invalidateQueries({ queryKey: problemKeys.detail(id) });
    void queryClient.invalidateQueries({ queryKey: problemKeys.links(id) });
    void queryClient.invalidateQueries({ queryKey: problemKeys.investigators(id) });
  });
  if (record.isLoading) return <Skeleton active />;
  if (record.data === undefined) {
    return (
      <Result
        status="404"
        title={t('problems.not_found')}
        extra={<Link to="/problems">{t('nav.problems')}</Link>}
      />
    );
  }
  return <ProblemView item={record.data} navigate={navigate} locale={locale} dates={dates} />;
}

function ProblemView({
  item,
  navigate,
  locale,
  dates,
}: {
  item: Problem;
  navigate: ReturnType<typeof useNavigate>;
  locale: string;
  dates: ReturnType<typeof useDateTime>;
}) {
  const t = useLabel();
  const catalogue = useProblemCatalogue();
  const act = useProblemAction(item.id);
  const status = useStatusActions(item, catalogue.data, act);
  const copy = useCopyProblem();
  const canEdit = item.operations.find((o) => o.action === 'edit')?.allowed === true;
  const me = useSession().data?.user.id ?? '';
  const copyAction: RecordAction = {
    key: 'copy',
    label: t('problems.copy'),
    allowed: !copy.isPending,
    onClick: () => {
      copy.mutate(
        { id: item.id, key: crypto.randomUUID() },
        {
          onSuccess: (made) => void navigate(`/problems/${made.id}`),
          onError: reportError,
        },
      );
    },
  };
  const problemType = (catalogue.data?.problem_types ?? []).find(
    (v) => v.code === item.problem_type,
  );
  return (
    <>
      <RecordPage
        testId="prb-record"
        header={
          <RecordHeader
            icon={<BugOutlined />}
            typeLabel={t('problems.record_type')}
            displayId={item.display_id}
            title={item.subject}
            testIds={{ id: 'prb-display-id', title: 'prb-heading' }}
            tags={
              <>
                <StatusTag status={item.status} catalogue={catalogue.data} />
                <PriorityTag priority={item.priority} source={item.priority_source} />
              </>
            }
            meta={[
              <span key="by">
                {t('problems.reported_by', { name: personName(item.people, item.requester_id) })}
              </span>,
              <span key="created">
                {t('incidents.created_on', { date: dates.format(item.created_at) })}
              </span>,
            ]}
          />
        }
        actions={
          <ActionBar actions={[...status.actions, copyAction]} max={3} testId="prb-actions" />
        }
        panel={
          <PropertiesPanel
            testId="prb-panel"
            sections={[
              {
                key: 'properties',
                title: t('problems.properties'),
                children: (
                  <>
                    <PropertyRow label={t('problems.owner')}>
                      {personName(item.people, item.technician_id)}
                    </PropertyRow>
                    <PropertyRow label={t('work_item.field.problem_type')}>
                      {problemType === undefined
                        ? ''
                        : labelled(problemType.labels, locale, () =>
                            t(`problem_type.${problemType.code}`),
                          )}
                    </PropertyRow>
                    <PropertyRow label={t('problems.target_date')}>
                      {item.resolution_due_at === null ? '' : dates.format(item.resolution_due_at)}
                    </PropertyRow>
                    <PropertyRow label={t('problems.lifecycle')}>
                      {t(`lifecycle.${item.lifecycle}`)}
                    </PropertyRow>
                  </>
                ),
              },
              {
                key: 'investigators',
                title: t('problems.investigators.title'),
                testId: 'prb-investigators-section',
                children: <Investigators id={item.id} canEdit={canEdit} me={me} />,
              },
              {
                key: 'incidents',
                title: t('problems.incidents'),
                children: <CausedIncidents id={item.id} />,
              },
            ]}
          />
        }
      >
        <Flex vertical gap={16} style={{ padding: 16 }}>
          {item.lifecycle === 'guided_analysis' && <GuidedSteps record={item} />}
          {item.description === null || item.description === '' ? (
            <Typography.Text type="secondary">{t('problems.no_description')}</Typography.Text>
          ) : (
            <RichTextView html={item.description} testId="prb-description" />
          )}
        </Flex>
      </RecordPage>
      {status.dialogs}
    </>
  );
}
