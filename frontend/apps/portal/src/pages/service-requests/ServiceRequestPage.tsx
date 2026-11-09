import { CheckOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Flex,
  Input,
  List,
  Modal,
  Progress,
  Result,
  Skeleton,
  Typography,
} from 'antd';
import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import {
  portalRequestKeys,
  serviceRequestKeys,
  useAnswerRequest,
  useApprovals,
  useCatalogItem,
  usePortalRequest,
  usePortalRequestSteps,
  useSession,
  useWithdrawRequest,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useRecordEvents } from '@supportx/realtime';
import {
  reportError,
  RichTextView,
  useAnswerWords,
  useAppearance,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { PortalStatusTag } from '../requests/PortalStatusTag';

/**
 * One service request as its requester sees it (WP-030 D9; REQ-SR-051, -061, -062): the plain
 * status, the item and the answers given, the approval (only what the tenant shows requesters,
 * REQ-SR-024 AC3), the fulfilment as steps (internal ones without a name), and Withdraw while
 * it waits for approval. Live on the requester channel, like the portal's incidents.
 */
export function ServiceRequestPage() {
  const t = useLabel();
  const answerWords = useAnswerWords();
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const submitted = params.get('submitted') === '1';
  const listFormat = useListFormat();
  const { format } = useDateTime();
  const { locale } = useAppearance();
  const queryClient = useQueryClient();
  const me = useSession().data?.user.id;
  const record = usePortalRequest(id);
  const steps = usePortalRequestSteps(id);
  const approvals = useApprovals(id);
  const item = useCatalogItem(record.data?.catalog_item_id ?? undefined);
  const withdraw = useWithdrawRequest();
  const [asking, setAsking] = useState(false);
  const answer = useAnswerRequest(id);
  const [notDone, setNotDone] = useState(false);
  const [why, setWhy] = useState('');
  useRecordEvents('portal_wi', id, () => {
    void queryClient.invalidateQueries({ queryKey: portalRequestKeys.detail(id) });
    void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.detail(id) });
  });
  if (record.isLoading) return <Skeleton active />;
  if (record.data === undefined) {
    return (
      <Result
        status="404"
        title={t('portal.request.not_found')}
        extra={<Link to="/service-requests">{t('portal.service_requests.title')}</Link>}
      />
    );
  }
  const r = record.data;
  const questions = item.data?.questions ?? [];
  const mine = me !== undefined && [r.requester_id, r.on_behalf_of_id].includes(me);
  const total = steps.data?.total ?? 0;
  const done = steps.data?.done ?? 0;
  const decided = (approvals.data?.items ?? []).filter((a) => a.state !== 'pending');
  const waitingOn = (approvals.data?.items ?? [])
    .filter((a) => a.state === 'pending')
    .map((a) =>
      a.approver_id === null
        ? t('portal.next.approval_admins')
        : (approvals.data?.people[a.approver_id]?.display_name ?? ''),
    )
    .filter((name) => name !== '');
  return (
    <Flex vertical gap={16} style={{ maxWidth: 760 }}>
      {submitted && (
        <Alert
          type="success"
          showIcon
          data-testid="portal-next"
          message={t('portal.next.title', { id: r.display_id })}
          description={
            <Flex vertical gap={8}>
              {waitingOn.length > 0 && (
                <Typography.Text data-testid="portal-next-approval">
                  {t('portal.next.waiting_for', { names: listFormat(waitingOn, 'conjunction') })}
                </Typography.Text>
              )}
              {r.resolution_due_at != null && (
                <Typography.Text data-testid="portal-next-due">
                  {t('portal.next.expected', { date: format(r.resolution_due_at) })}
                </Typography.Text>
              )}
              <Typography.Text>{t('portal.next.follow')}</Typography.Text>
              <Flex gap={8} wrap>
                <Link to="/catalog" data-testid="portal-next-another">
                  {t('portal.next.another')}
                </Link>
                <Link to="/" data-testid="portal-next-home">
                  {t('portal.next.home')}
                </Link>
              </Flex>
            </Flex>
          }
        />
      )}
      <Link to="/service-requests">{t('portal.service_requests.back')}</Link>
      <Flex justify="space-between" align="center" gap={12} wrap>
        <Typography.Title level={1} style={{ margin: 0 }}>
          <span dir="ltr" data-testid="portal-service-request-id">
            {r.display_id}
          </span>{' '}
          · <bdi>{r.subject}</bdi>
        </Typography.Title>
        <PortalStatusTag status={r.portal_status} />
      </Flex>
      {r.portal_status === 'resolved' && mine && (
        <Card title={t('portal.service_requests.received_title')} data-testid="portal-receipt">
          {r.resolution != null && <RichTextView html={r.resolution} />}
          {notDone ? (
            <Flex vertical gap={8}>
              <Input.TextArea
                aria-label={t('portal.fix.why')}
                value={why}
                autoSize={{ minRows: 2 }}
                onChange={(e) => {
                  setWhy(e.target.value);
                }}
                data-testid="portal-receipt-why"
              />
              <Button
                danger
                disabled={why.trim() === ''}
                loading={answer.isPending}
                onClick={() => {
                  answer.mutate(
                    { confirmed: false, comment: why.trim() },
                    { onError: reportError },
                  );
                }}
              >
                {t('portal.fix.reject_send')}
              </Button>
            </Flex>
          ) : (
            <Flex gap={8} wrap>
              <Button
                type="primary"
                loading={answer.isPending}
                onClick={() => {
                  answer.mutate({ confirmed: true }, { onError: reportError });
                }}
                data-testid="portal-receipt-confirm"
              >
                {t('portal.service_requests.received_yes')}
              </Button>
              <Button
                onClick={() => {
                  setNotDone(true);
                }}
                data-testid="portal-receipt-reject"
              >
                {t('portal.service_requests.received_no')}
              </Button>
            </Flex>
          )}
        </Card>
      )}
      {r.approval_status === 'pending' && mine && (
        <Button
          // Its own width, not the column's (QA6-SR-04).
          style={{ alignSelf: 'flex-start' }}
          onClick={() => {
            setAsking(true);
          }}
          data-testid="portal-withdraw"
        >
          {t('requests.withdraw')}
        </Button>
      )}
      <Modal
        open={asking}
        title={t('requests.withdraw')}
        okText={t('requests.withdraw')}
        okButtonProps={{ danger: true, loading: withdraw.isPending }}
        cancelText={t('actions.cancel')}
        onCancel={() => {
          setAsking(false);
        }}
        onOk={() => {
          withdraw.mutate(
            { recordId: r.id, version: r.version },
            {
              onSuccess: () => {
                setAsking(false);
                void queryClient.invalidateQueries({ queryKey: portalRequestKeys.all });
              },
              onError: reportError,
            },
          );
        }}
      >
        {t('requests.withdraw_confirm')}
      </Modal>
      {/* On a white card, labels beside their answers, no grey label cells (QA6-SR-04). */}
      <Card title={t('requests.item_details')} data-testid="portal-service-request-details">
        <Descriptions size="small" column={1} data-testid="portal-service-request-answers">
          {questions.map((q) => (
            <Descriptions.Item key={q.key} label={q.label[locale] ?? q.label.en ?? q.key}>
              {answerWords(q, r.answers?.[q.key])}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </Card>
      {decided.length > 0 && (
        <List
          header={<Typography.Text strong>{t('requests.approvals')}</Typography.Text>}
          bordered
          dataSource={decided}
          data-testid="portal-service-request-approvals"
          renderItem={(a) => (
            <List.Item key={a.id}>
              <Flex vertical gap={4}>
                <Typography.Text>{t(`approval_state.${a.state}`)}</Typography.Text>
                {a.comment != null && <bdi>{a.comment}</bdi>}
              </Flex>
            </List.Item>
          )}
        />
      )}
      {total > 0 && (
        <Card title={t('requests.tasks')} data-testid="portal-service-request-steps">
          <Progress percent={Math.round((done / total) * 100)} />
          <List
            size="small"
            dataSource={steps.data?.items ?? []}
            renderItem={(s) => (
              <List.Item key={s.position}>
                {s.title === null ? (
                  t('portal.service_requests.step', { n: s.position, total })
                ) : (
                  <bdi>{s.title}</bdi>
                )}{' '}
                {s.done && <CheckOutlined aria-label={t('portal.service_requests.step_done')} />}
              </List.Item>
            )}
          />
        </Card>
      )}
    </Flex>
  );
}
