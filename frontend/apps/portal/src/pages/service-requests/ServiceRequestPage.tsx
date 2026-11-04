import { CheckOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Card,
  Descriptions,
  Flex,
  List,
  Modal,
  Progress,
  Result,
  Skeleton,
  Typography,
} from 'antd';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  portalRequestKeys,
  serviceRequestKeys,
  useApprovals,
  useCatalogItem,
  usePortalRequest,
  usePortalRequestSteps,
  useSession,
  useWithdrawRequest,
} from '@supportx/api-client';
import { useRecordEvents } from '@supportx/realtime';
import { reportError, useAppearance, useLabel } from '@supportx/ui';

import { PortalStatusTag } from '../requests/PortalStatusTag';

function answerText(value: unknown): string {
  if (value === null || value === undefined) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/**
 * One service request as its requester sees it (WP-030 D9; REQ-SR-051, -061, -062): the plain
 * status, the item and the answers given, the approval (only what the tenant shows requesters,
 * REQ-SR-024 AC3), the fulfilment as steps (internal ones without a name), and Withdraw while
 * it waits for approval. Live on the requester channel, like the portal's incidents.
 */
export function ServiceRequestPage() {
  const t = useLabel();
  const { id = '' } = useParams();
  const { locale } = useAppearance();
  const queryClient = useQueryClient();
  const me = useSession().data?.user.id;
  const record = usePortalRequest(id);
  const steps = usePortalRequestSteps(id);
  const approvals = useApprovals(id);
  const item = useCatalogItem(record.data?.catalog_item_id ?? undefined);
  const withdraw = useWithdrawRequest();
  const [asking, setAsking] = useState(false);
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
  return (
    <Flex vertical gap={16} style={{ maxWidth: 760 }}>
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
      {r.approval_status === 'pending' && mine && (
        <Button
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
      <Descriptions
        title={t('requests.item_details')}
        bordered
        size="small"
        column={1}
        data-testid="portal-service-request-answers"
      >
        {questions.map((q) => (
          <Descriptions.Item key={q.key} label={q.label[locale] ?? q.label.en ?? q.key}>
            {answerText(r.answers?.[q.key])}
          </Descriptions.Item>
        ))}
      </Descriptions>
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
