import { useQueryClient } from '@tanstack/react-query';
import { Descriptions, Result, Skeleton, Space } from 'antd';
import { Link, useNavigate, useParams } from 'react-router';

import {
  serviceRequestKeys,
  useCatalogItem,
  useServiceRequest,
  useSession,
  useWithdrawRequest,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import {
  PageHeader,
  reportError,
  ToneTag,
  useAppearance,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { ApprovalsPanel, WithdrawButton } from './Approvals';
import { itemName } from './items';

function answerText(value: unknown): string {
  if (value === null || value === undefined) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/**
 * One service request's summary (WP-030 s1): the item and its answers (REQ-SR-003 AC1), status,
 * approval status, priority and its source, its approvals with Approve / Reject for the approver
 * and Withdraw for the requester while it waits (WP-030 s2), live on the record channel.
 */
export function RequestPage() {
  const t = useLabel();
  const { id = '' } = useParams();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const record = useServiceRequest(id);
  const item = useCatalogItem(record.data?.catalog_item_id ?? undefined);
  const me = useSession().data?.user.id;
  const withdraw = useWithdrawRequest();
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
  const r = record.data;
  const questions = item.data?.questions ?? [];
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <PageHeader
        title={
          <>
            <span dir="ltr">{r.display_id}</span> · <bdi>{r.subject}</bdi>
          </>
        }
        back={{ label: t('nav.requests'), onClick: () => void navigate('/requests') }}
        extra={
          r.approval_status === 'pending' &&
          me !== undefined &&
          [r.requester_id, r.on_behalf_of_id].includes(me) && (
            <WithdrawButton
              pending={withdraw.isPending}
              onWithdraw={() => {
                withdraw.mutate({ recordId: r.id, version: r.version }, { onError: reportError });
              }}
            />
          )
        }
      />
      <Space wrap>
        <ToneTag tone="info" testId="sr-status">
          {t(`work_item_status.${r.status}`)}
        </ToneTag>
        {r.approval_status != null && (
          <ToneTag
            tone={
              r.approval_status === 'rejected'
                ? 'error'
                : r.approval_status === 'pending'
                  ? 'warning'
                  : 'success'
            }
            testId="sr-approval"
          >
            {t(`approval_status.${r.approval_status}`)}
          </ToneTag>
        )}
      </Space>
      <Descriptions bordered size="small" column={1} data-testid="sr-details">
        <Descriptions.Item label={t('requests.item')}>
          {itemName(item.data, locale)}
        </Descriptions.Item>
        <Descriptions.Item label={t('incidents.col.priority')}>
          {t(`priority.${r.priority}`)} · {t(`priority_source.${r.priority_source}`)}
        </Descriptions.Item>
        <Descriptions.Item label={t('incidents.col.updated')}>
          {format(r.updated_at)}
        </Descriptions.Item>
      </Descriptions>
      <Descriptions
        title={t('requests.item_details')}
        bordered
        size="small"
        column={1}
        data-testid="sr-answers"
      >
        {questions.map((q) => (
          <Descriptions.Item key={q.key} label={q.label[locale] ?? q.label.en ?? q.key}>
            {answerText(r.answers?.[q.key])}
          </Descriptions.Item>
        ))}
      </Descriptions>
      {r.approval_status != null && r.approval_status !== 'not_needed' && (
        <ApprovalsPanel recordId={r.id} />
      )}
    </Space>
  );
}
