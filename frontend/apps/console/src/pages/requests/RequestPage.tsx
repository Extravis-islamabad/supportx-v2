import { ShoppingCartOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, Descriptions, Flex, Result, Skeleton, Tabs, Typography } from 'antd';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  serviceRequestKeys,
  useCatalogItem,
  useApprovals,
  useRequestTasks,
  useServiceRequest,
  useSession,
  useStructure,
  useUnits,
  useWithdrawRequest,
  type ServiceRequest,
  type ReplyMode,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import {
  EmptyText,
  ActionBar,
  PropertiesPanel,
  PropertyRow,
  RecordHeader,
  RecordPage,
  reportError,
  ToneTag,
  useAccess,
  useAnswerWords,
  useAppearance,
  useDateTime,
  useLabel,
  useLicence,
  usePageCrumbs,
} from '@supportx/ui';

import { IncidentConversation, type Typing } from '../incidents/IncidentConversation';
import { labelled, personName } from '../incidents/labels';
import { PriorityTag, SlaTag } from '../incidents/tags';
import { ApprovalsPanel, WithdrawButton } from './Approvals';
import { RequestTasks } from './RequestTasks';
import { IncidentSla } from '../incidents/IncidentSla';
import { itemName } from './items';

const NO_TYPING: Typing = {};

/**
 * One service request on the record template (D-147 template A; WP-030's content): the header
 * with its ID, subject and ONE status chip (the approval's state lives in the panel and the
 * Approvals tab, never a second "Awaiting approval" chip, Haider's point), the requester and
 * the request's properties in the panel, and the conversation, item details, approvals and
 * fulfilment tasks in tabs. Live on the record channel.
 */
export function RequestPage() {
  const t = useLabel();
  const { id = '' } = useParams();
  const queryClient = useQueryClient();
  const record = useServiceRequest(id);
  useRecordChannel('wi', id === '' ? undefined : id, () => {
    void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.detail(id) });
  });
  if (record.isLoading) return <Skeleton active />;
  if (record.data === undefined) {
    return (
      <Result
        status="404"
        title={t('requests.not_found')}
        extra={<Link to="/requests">{t('nav.requests')}</Link>}
      />
    );
  }
  return <RequestRecord r={record.data} />;
}

/** Who decided each approval, and when (Haider E3); the tab keeps the full list and buttons. */
function ApprovalsSummary({ recordId }: { recordId: string }) {
  const t = useLabel();
  const { format } = useDateTime();
  const approvals = useApprovals(recordId);
  const people = approvals.data?.people ?? {};
  const decided = (approvals.data?.items ?? []).filter((a) => a.decided_at != null);
  if (decided.length === 0) {
    return <EmptyText>{t('requests.approvals_none_decided')}</EmptyText>;
  }
  return (
    <Flex vertical gap={4} data-testid="sr-approvals-summary">
      {decided.map((a) => (
        <Typography.Text key={a.id} data-testid={`sr-approval-summary-${a.id}`}>
          {t(`approval_state.${a.state}`)} ·{' '}
          {t('requests.decided_summary', {
            name:
              a.decided_by == null
                ? t('requests.approval_admins')
                : (people[a.decided_by]?.display_name ?? ''),
            when: format(a.decided_at ?? ''),
          })}
        </Typography.Text>
      ))}
    </Flex>
  );
}

function RequestRecord({ r }: { r: ServiceRequest }) {
  const t = useLabel();
  const answerWords = useAnswerWords();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const item = useCatalogItem(r.catalog_item_id ?? undefined);
  const me = useSession().data?.user.id;
  const withdraw = useWithdrawRequest();
  const { can } = useAccess();
  const [replyRequest, setReplyRequest] = useState(0);
  const [replyMode, setReplyMode] = useState<ReplyMode>('reply');
  const questions = item.data?.questions ?? [];
  const sites = useUnits('sites');
  const siteName = sites.data?.find((u) => u.id === r.site_id)?.name;
  const mayWithdraw =
    r.approval_status === 'pending' &&
    me !== undefined &&
    [r.requester_id, r.on_behalf_of_id].includes(me);
  const reply = r.conversation_actions.find((a) => a.action === 'reply');
  const hasApprovals = r.approval_status != null && r.approval_status !== 'not_needed';
  // D-154 "E1 follows d": every required task done but nobody on it, so it is not fulfilled
  // by itself; the record says so until someone takes it.
  const tasks = useRequestTasks(r.id);
  const required = (tasks.data?.items ?? []).filter((task) => task.from_plan && task.required);
  const readyToFulfil =
    r.status_category === 'open' &&
    r.technician_id === null &&
    required.length > 0 &&
    required.every((task) => task.status === 'done');
  return (
    <>
      <RequestCrumbs item={r} />
      <RecordPage
        testId="sr-record"
        alerts={
          readyToFulfil ? (
            <Alert
              type="warning"
              showIcon
              role="status"
              message={t('requests.ready_to_fulfil')}
              data-testid="sr-ready-to-fulfil"
            />
          ) : undefined
        }
        header={
          <RecordHeader
            icon={<ShoppingCartOutlined />}
            kind="service_request"
            typeLabel={t('requests.record_type')}
            displayId={r.display_id}
            title={r.subject}
            testIds={{ id: 'sr-display-id', title: 'sr-heading' }}
            tags={
              <>
                <ToneTag tone="info" testId="sr-status">
                  {t(`work_item_status.${r.status}`)}
                </ToneTag>
                <PriorityTag priority={r.priority} source={r.priority_source} />
                <SlaTag
                  policyId={r.sla_policy_id}
                  dueAt={r.resolution_due_at}
                  state={r.resolution_sla_state}
                  resolvedAt={r.resolved_at}
                  format={dates.format}
                />
              </>
            }
            meta={[
              <span key="by">
                {t('requests.requested_by', { name: personName(r.people, r.requester_id) })}
              </span>,
              <span key="created">
                {t('incidents.created_on', { date: dates.format(r.created_at) })}
              </span>,
            ]}
          />
        }
        actions={
          <ActionBar
            testId="sr-actions"
            max={3}
            lead={
              mayWithdraw ? (
                <WithdrawButton
                  pending={withdraw.isPending}
                  onWithdraw={() => {
                    withdraw.mutate(
                      { recordId: r.id, version: r.version },
                      { onError: reportError },
                    );
                  }}
                />
              ) : undefined
            }
            actions={
              reply === undefined
                ? []
                : [
                    {
                      key: 'reply',
                      label: t('reply_mode.reply'),
                      allowed: reply.allowed,
                      primary: true,
                      rank: 0,
                      onClick: () => {
                        setReplyMode('reply');
                        setReplyRequest((n) => n + 1);
                      },
                      testId: 'sr-reply',
                      // D-155: the record's one Reply, as on incidents.
                      variants: (['reply_all', 'forward'] as const).map((mode) => ({
                        key: mode,
                        label: t(`reply_mode.${mode}`),
                        testId: `sr-${mode}`,
                        onClick: () => {
                          setReplyMode(mode);
                          setReplyRequest((n) => n + 1);
                        },
                      })),
                    },
                  ]
            }
          />
        }
        panel={
          <PropertiesPanel
            testId="sr-panel"
            sections={[
              {
                key: 'requester',
                title: t('requests.requester'),
                children: (
                  // A person card, not a row repeating its title: the name, then how to reach
                  // them and where they are, when known.
                  <Flex vertical gap={2} data-testid="sr-requester">
                    <Typography.Text strong>
                      <bdi>{personName(r.people, r.requester_id)}</bdi>
                    </Typography.Text>
                    {r.people[r.requester_id]?.email && (
                      <Typography.Text type="secondary" copyable>
                        <bdi dir="ltr">{r.people[r.requester_id]?.email}</bdi>
                      </Typography.Text>
                    )}
                    {siteName !== undefined && (
                      <Typography.Text type="secondary">
                        <bdi>{siteName}</bdi>
                      </Typography.Text>
                    )}
                    {r.on_behalf_of_id !== null && (
                      <Typography.Text type="secondary">
                        {t('requests.for_person', {
                          name: personName(r.people, r.on_behalf_of_id),
                        })}
                      </Typography.Text>
                    )}
                  </Flex>
                ),
              },
              {
                key: 'properties',
                title: t('requests.properties'),
                children: (
                  <div data-testid="sr-details">
                    <PropertyRow label={t('requests.item')}>
                      <bdi>{itemName(item.data, locale)}</bdi>
                    </PropertyRow>
                    {/* Pending is the status chip's own words: only a decided approval adds one. */}
                    {hasApprovals && r.approval_status !== 'pending' && (
                      <PropertyRow label={t('requests.approval')}>
                        <span data-testid="sr-approval">
                          {t(`approval_status.${r.approval_status ?? 'not_needed'}`)}
                        </span>
                      </PropertyRow>
                    )}
                    <PropertyRow label={t('work_item.field.technician_id')}>
                      {r.technician_id === null ? (
                        <Typography.Text type="secondary">
                          {t('incidents.unassigned')}
                        </Typography.Text>
                      ) : (
                        <bdi>{personName(r.people, r.technician_id)}</bdi>
                      )}
                    </PropertyRow>
                    <PropertyRow label={t('incidents.col.updated')}>
                      {dates.format(r.updated_at)}
                    </PropertyRow>
                  </div>
                ),
              },
              // Haider E3: the Service level card, as on incidents (read-only here).
              {
                key: 'sla',
                title: t('incidents.panel.sla'),
                testId: 'sr-panel-sla',
                children: (
                  <div data-testid="sr-sla-card">
                    <IncidentSla item={r} base="service-requests" />
                  </div>
                ),
              },
              ...(hasApprovals
                ? [
                    {
                      key: 'approvals',
                      title: t('requests.approvals'),
                      testId: 'sr-panel-approvals',
                      children: <ApprovalsSummary recordId={r.id} />,
                    },
                  ]
                : []),
            ]}
          />
        }
      >
        <Tabs
          data-testid="sr-tabs"
          destroyOnHidden
          // While it waits for approval it opens on the approvals: the approver's buttons first.
          defaultActiveKey={r.approval_status === 'pending' ? 'approvals' : 'conversation'}
          items={[
            {
              key: 'conversation',
              label: (
                <span data-testid="sr-tab-conversation">{t('requests.tab.conversation')}</span>
              ),
              children: (
                <IncidentConversation
                  item={r}
                  typing={NO_TYPING}
                  replyRequest={replyRequest}
                  replyMode={replyMode}
                  base="service-requests"
                />
              ),
            },
            {
              key: 'details',
              label: <span data-testid="sr-tab-details">{t('requests.item_details')}</span>,
              children: (
                <Descriptions size="small" column={1} data-testid="sr-answers">
                  {questions.map((q) => (
                    <Descriptions.Item key={q.key} label={q.label[locale] ?? q.label.en ?? q.key}>
                      {answerWords(q, r.answers?.[q.key]) || (
                        <Typography.Text type="secondary">
                          {t('catalog.answer.not_given')}
                        </Typography.Text>
                      )}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              ),
            },
            ...(hasApprovals
              ? [
                  {
                    key: 'approvals',
                    label: <span data-testid="sr-tab-approvals">{t('requests.approvals')}</span>,
                    children: <ApprovalsPanel recordId={r.id} />,
                  },
                ]
              : []),
            {
              key: 'tasks',
              label: <span data-testid="sr-tab-tasks">{t('requests.tasks')}</span>,
              children: <RequestTasks recordId={r.id} canEdit={can('requests.edit')} />,
            },
          ]}
        />
      </RecordPage>
    </>
  );
}

/** desk / Service requests / SR-3, as on the incident record. */
function RequestCrumbs({ item }: { item: ServiceRequest }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const esm = useLicence().has('esm');
  const desks = useStructure('desks', esm, true);
  const desk = esm ? desks.data?.find((d) => d.id === item.desk_id) : undefined;
  usePageCrumbs([
    ...(desk ? [{ label: labelled(desk.labels, locale, () => t(`desk.${desk.code}`)) }] : []),
    { label: t('nav.requests'), path: '/requests' },
    { label: item.display_id },
  ]);
  return null;
}
