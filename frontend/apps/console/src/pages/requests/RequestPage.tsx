import { ShoppingCartOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Descriptions, Result, Skeleton, Tabs, Typography } from 'antd';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  serviceRequestKeys,
  useCatalogItem,
  useServiceRequest,
  useSession,
  useWithdrawRequest,
  type ServiceRequest,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import {
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
} from '@supportx/ui';

import { IncidentConversation, type Typing } from '../incidents/IncidentConversation';
import { personName } from '../incidents/labels';
import { PriorityTag, SlaTag } from '../incidents/tags';
import { ApprovalsPanel, WithdrawButton } from './Approvals';
import { RequestTasks } from './RequestTasks';
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
  const questions = item.data?.questions ?? [];
  const mayWithdraw =
    r.approval_status === 'pending' &&
    me !== undefined &&
    [r.requester_id, r.on_behalf_of_id].includes(me);
  const reply = r.conversation_actions.find((a) => a.action === 'reply');
  const hasApprovals = r.approval_status != null && r.approval_status !== 'not_needed';
  return (
    <RecordPage
      testId="sr-record"
      header={
        <RecordHeader
          icon={<ShoppingCartOutlined />}
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
                  withdraw.mutate({ recordId: r.id, version: r.version }, { onError: reportError });
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
                      setReplyRequest((n) => n + 1);
                    },
                    testId: 'sr-reply',
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
                <>
                  <PropertyRow label={t('work_item.field.requester_id')}>
                    <bdi>{personName(r.people, r.requester_id)}</bdi>
                  </PropertyRow>
                  {r.on_behalf_of_id !== null && (
                    <PropertyRow label={t('requests.requested_for')}>
                      <bdi>{personName(r.people, r.on_behalf_of_id)}</bdi>
                    </PropertyRow>
                  )}
                </>
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
            label: <span data-testid="sr-tab-conversation">{t('requests.tab.conversation')}</span>,
            children: (
              <IncidentConversation
                item={r}
                typing={NO_TYPING}
                replyRequest={replyRequest}
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
  );
}
