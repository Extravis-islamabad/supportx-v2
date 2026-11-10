import { BugOutlined, CloseOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Flex, Result, Select, Skeleton, Steps, Tabs, Typography } from 'antd';
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
  useProblemPeople,
  useSession,
  type Problem,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import {
  ActionBar,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  RichTextView,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
  usePageCrumbs,
  type RecordAction,
} from '@supportx/ui';

import { labelled, personName } from '../incidents/labels';
import { useStatusActions } from '../incidents/StatusActions';
import { PriorityTag, StatusTag } from '../incidents/tags';
import { useDebounced } from '../../useDebounced';
import { IncidentHistory } from '../incidents/IncidentHistory';
import { IncidentTasks, IncidentWorklogs } from '../incidents/IncidentParts';
import { ProblemAnalysis, ProblemEvidence } from './ProblemAnalysis';
import { KnownErrorTag } from './KnownErrors';
import { CausedIncidents, MergeDialog, MergedBanner, RelatedProblems } from './ProblemLinks';
import { useKnownErrorAction } from './useKnownErrorAction';
import { FollowUpDialog } from './FollowUp';
import { MessageRequestersDialog } from './MessageRequesters';
import { ProblemApprovals, RequestApprovalDialog } from './ProblemApprovals';
import { useActionReason } from '../incidents/actionReason';
import { AssignDialog } from '../incidents/assign';

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
 * Live on the record channel. Tabs: overview, analysis and evidence (WP-044b); tasks and the
 * conversation come with WP-044b/c.
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
    // A linked or resolved incident moves the figures and the timeline (REQ-PRB-032 AC2).
    void queryClient.invalidateQueries({ queryKey: problemKeys.impact(id) });
    void queryClient.invalidateQueries({ queryKey: problemKeys.evidence(id) });
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
  return (
    <ProblemView
      item={record.data}
      navigate={navigate}
      locale={locale}
      dates={dates}
      reload={async () => (await record.refetch()).data}
    />
  );
}

function ProblemView({
  item,
  navigate,
  locale,
  dates,
  reload,
}: {
  item: Problem;
  navigate: ReturnType<typeof useNavigate>;
  locale: string;
  dates: ReturnType<typeof useDateTime>;
  reload: () => Promise<unknown>;
}) {
  const t = useLabel();
  const catalogue = useProblemCatalogue();
  const act = useProblemAction(item.id);
  const status = useStatusActions(item, catalogue.data, act);
  const copy = useCopyProblem();
  const canEdit = item.operations.find((o) => o.action === 'edit')?.allowed === true;
  const me = useSession().data?.user.id ?? '';
  const knownError = useKnownErrorAction(item);
  const reasonText = useActionReason();
  // The group and owner, the incident's dialog with the problems' rules (WP-044c S1).
  const [assigning, setAssigning] = useState(false);
  const assignState = item.operations.find((o) => o.action === 'assign');
  const assignAction: RecordAction | null =
    assignState === undefined
      ? null
      : {
          key: 'assign',
          label: t('work_item_operation.assign'),
          allowed: assignState.allowed,
          whyNot:
            !assignState.allowed && assignState.reason != null
              ? reasonText(assignState)
              : undefined,
          testId: 'prb-op-assign',
          onClick: () => {
            setAssigning(true);
          },
        };
  const [asking, setAsking] = useState(false);
  const askAction: RecordAction = {
    key: 'ask_approval',
    label: t('problems.approvals.ask'),
    allowed: canEdit && item.status_category !== 'closed' && item.approval_status !== 'pending',
    onClick: () => {
      setAsking(true);
    },
  };
  const [following, setFollowing] = useState(false);
  const followUpAction: RecordAction = {
    key: 'follow_up',
    label: t('problems.follow_up.title'),
    allowed: canEdit,
    testId: 'prb-op-follow-up',
    onClick: () => {
      setFollowing(true);
    },
  };
  const [messaging, setMessaging] = useState(false);
  const messageAction: RecordAction = {
    key: 'message_requesters',
    label: t('problems.message.title'),
    allowed: canEdit,
    onClick: () => {
      setMessaging(true);
    },
  };
  const [merging, setMerging] = useState(false);
  const mergeAction: RecordAction = {
    key: 'merge',
    label: t('problems.merge.action'),
    allowed: canEdit && item.status_category !== 'closed' && item.status !== 'merged',
    onClick: () => {
      setMerging(true);
    },
  };
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
  // The record as a document (WP-044c S1): the browser's print, with the navigation, the
  // actions and the editors left out by the page's print rules (AppearanceProvider).
  const printAction: RecordAction = {
    key: 'print',
    label: t('problems.print'),
    allowed: true,
    testId: 'prb-print',
    onClick: () => {
      window.print();
    },
  };
  const problemType = (catalogue.data?.problem_types ?? []).find(
    (v) => v.code === item.problem_type,
  );
  return (
    <>
      <ProblemCrumbs displayId={item.display_id} />
      <RecordPage
        testId="prb-record"
        header={
          <RecordHeader
            icon={<BugOutlined />}
            kind="problem"
            typeLabel={t('problems.record_type')}
            displayId={item.display_id}
            title={item.subject}
            testIds={{ id: 'prb-display-id', title: 'prb-heading' }}
            tags={
              <>
                <StatusTag status={item.status} catalogue={catalogue.data} />
                <PriorityTag priority={item.priority} source={item.priority_source} />
                <KnownErrorTag item={item} />
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
          <ActionBar
            actions={[
              ...(assignAction === null ? [] : [assignAction]),
              ...status.actions,
              knownError.action,
              askAction,
              messageAction,
              followUpAction,
              copyAction,
              printAction,
              mergeAction,
            ]}
            max={3}
            testId="prb-actions"
          />
        }
        panel={
          <PropertiesPanel
            testId="prb-panel"
            sections={[
              {
                key: 'properties',
                title: t('problems.properties'),
                // Template A (QA10V-09): the fields with a value, then "Add details (n)" for
                // the empty ones; never an empty "Problem type" row.
                children: (
                  <PropertyList
                    testId="prb-properties"
                    items={[
                      {
                        key: 'owner',
                        label: t('problems.owner'),
                        content: personName(item.people, item.technician_id),
                        filled: item.technician_id !== null,
                      },
                      {
                        key: 'problem_type',
                        label: t('work_item.field.problem_type'),
                        content:
                          problemType === undefined
                            ? ''
                            : labelled(problemType.labels, locale, () =>
                                t(`problem_type.${problemType.code}`),
                              ),
                        filled: problemType !== undefined,
                      },
                      {
                        key: 'target_date',
                        label: t('problems.target_date'),
                        content:
                          item.resolution_due_at === null
                            ? ''
                            : dates.format(item.resolution_due_at),
                        filled: item.resolution_due_at !== null,
                      },
                      {
                        key: 'lifecycle',
                        label: t('problems.lifecycle'),
                        content: t(`lifecycle.${item.lifecycle}`),
                        filled: true,
                      },
                    ]}
                  />
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
                children: <CausedIncidents id={item.id} canEdit={canEdit} />,
              },
              {
                key: 'approvals',
                title: t('problems.approvals.title'),
                children: <ProblemApprovals item={item} />,
              },
              {
                key: 'related',
                title: t('problems.related.title'),
                children: <RelatedProblems id={item.id} canEdit={canEdit} />,
              },
            ]}
          />
        }
      >
        {/* No inset of its own: the tabs line up with the incident's and request's (QA10V-18). */}
        <Flex vertical gap={16}>
          <MergedBanner item={item} />
          {item.lifecycle === 'guided_analysis' && <GuidedSteps record={item} />}
          <Tabs
            data-testid="prb-tabs"
            destroyOnHidden
            items={[
              {
                key: 'overview',
                label: t('problems.tab.overview'),
                children:
                  item.description === null || item.description === '' ? (
                    <Typography.Text type="secondary">
                      {t('problems.no_description')}
                    </Typography.Text>
                  ) : (
                    <RichTextView html={item.description} testId="prb-description" />
                  ),
              },
              {
                key: 'analysis',
                label: <span data-testid="prb-tab-analysis">{t('problems.tab.analysis')}</span>,
                children: <ProblemAnalysis item={item} reload={reload} />,
              },
              {
                key: 'tasks',
                label: <span data-testid="prb-tab-tasks">{t('incidents.tab.tasks')}</span>,
                children: <IncidentTasks item={item} canEdit={canEdit} base="problems" />,
              },
              {
                key: 'worklogs',
                label: <span data-testid="prb-tab-worklogs">{t('incidents.tab.worklogs')}</span>,
                children: <IncidentWorklogs item={item} canEdit={canEdit} base="problems" />,
              },
              {
                key: 'history',
                label: (
                  <span data-testid="prb-tab-history">
                    {t('incidents.tab.history', { count: item.history_count })}
                  </span>
                ),
                children: <IncidentHistory id={item.id} base="problems" />,
              },
              {
                key: 'evidence',
                label: <span data-testid="prb-tab-evidence">{t('problems.tab.evidence')}</span>,
                children: <ProblemEvidence id={item.id} />,
              },
            ]}
          />
        </Flex>
      </RecordPage>
      {status.dialogs}
      {knownError.dialog}
      <FollowUpDialog
        item={item}
        open={following}
        onClose={() => {
          setFollowing(false);
        }}
      />
      <MessageRequestersDialog
        problemId={item.id}
        open={messaging}
        onClose={() => {
          setMessaging(false);
        }}
      />
      <RequestApprovalDialog
        item={item}
        open={asking}
        onClose={() => {
          setAsking(false);
        }}
      />
      <MergeDialog
        item={item}
        open={merging}
        onClose={() => {
          setMerging(false);
        }}
      />
      <AssignDialog
        item={item}
        open={assigning}
        base="problems"
        onClose={() => {
          setAssigning(false);
        }}
        refresh={reload}
      />
    </>
  );
}

/** Where the user is: "Problems › PRB-7", in the header and the browser tab (QA6-PRB-02). */
function ProblemCrumbs({ displayId }: { displayId: string }) {
  const t = useLabel();
  usePageCrumbs([{ label: t('nav.problems'), path: '/problems' }, { label: displayId }]);
  return null;
}
