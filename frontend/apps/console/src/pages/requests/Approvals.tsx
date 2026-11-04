import { Button, Empty, List, Modal, Space, Typography } from 'antd';
import { useState } from 'react';

import { useApprovals, type Approval } from '@supportx/api-client';
import { ToneTag, useDateTime, useLabel, WriteButton } from '@supportx/ui';

import { useDecision } from './useDecision';
type Tone = 'info' | 'success' | 'warning' | 'error';
const TONE: Record<Approval['state'], Tone> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'error',
  withdrawn: 'info',
  not_needed: 'info',
};

/**
 * A request's approvals (WP-030 s2, REQ-SR-024): every approver's entry with its decision,
 * when, where and the comment (a private one only for staff), why it went to a backup or the
 * administrators, and Approve / Reject for the approver (REQ-SR-025). Live: the record channel's
 * approvals signal refetches it (the page invalidates the record's queries).
 */
export function ApprovalsPanel({ recordId }: { recordId: string }) {
  const t = useLabel();
  const { format } = useDateTime();
  const approvals = useApprovals(recordId);
  const { dialog, start } = useDecision(recordId);
  const people = approvals.data?.people ?? {};
  const name = (id: string | null | undefined) =>
    id == null ? t('requests.approval_admins') : (people[id]?.display_name ?? '');
  const items = approvals.data?.items ?? [];
  if (approvals.isLoading) return null;
  return (
    <>
      <List
        header={<Typography.Text strong>{t('requests.approvals')}</Typography.Text>}
        bordered
        dataSource={items}
        data-testid="sr-approvals"
        locale={{ emptyText: <Empty description={t('requests.no_approvals')} /> }}
        renderItem={(a) => (
          <List.Item
            key={a.id}
            data-testid={`sr-approval-${a.id}`}
            actions={
              a.can_decide
                ? [
                    <WriteButton
                      key="approve"
                      type="primary"
                      onClick={() => {
                        start(a, 'approve');
                      }}
                      data-testid="approval-approve"
                    >
                      {t('requests.approve')}
                    </WriteButton>,
                    <WriteButton
                      key="reject"
                      danger
                      onClick={() => {
                        start(a, 'reject');
                      }}
                      data-testid="approval-reject"
                    >
                      {t('requests.reject')}
                    </WriteButton>,
                  ]
                : []
            }
          >
            <Space direction="vertical" size={2}>
              <Space wrap>
                <bdi>{name(a.approver_id)}</bdi>
                <Typography.Text type="secondary">
                  {t(`approval_origin.${a.origin}`)}
                </Typography.Text>
                <ToneTag tone={TONE[a.state]} testId="approval-state">
                  {t(`approval_state.${a.state}`)}
                </ToneTag>
                {a.self_approved && <ToneTag tone="warning">{t('requests.self_approved')}</ToneTag>}
              </Space>
              {a.route_reason != null && (
                <Typography.Text type="secondary" data-testid="approval-route-reason">
                  {t(`approval_route_reason.${a.route_reason}`)}
                </Typography.Text>
              )}
              {a.decided_at != null && (
                <Typography.Text type="secondary">
                  {t('requests.decided_by', {
                    name: name(a.decided_by),
                    when: format(a.decided_at),
                    channel: a.channel == null ? '' : t(`approval_channel.${a.channel}`),
                  })}
                </Typography.Text>
              )}
              {a.comment != null && (
                <Typography.Paragraph
                  style={{ marginBottom: 0 }}
                  data-testid="approval-comment-text"
                >
                  <bdi>{a.comment}</bdi>
                  {a.comment_private && (
                    <Typography.Text type="secondary">
                      {' '}
                      · {t('requests.private_comment')}
                    </Typography.Text>
                  )}
                </Typography.Paragraph>
              )}
            </Space>
          </List.Item>
        )}
      />
      {dialog}
    </>
  );
}

/** Withdraw while it waits (REQ-SR-061): the requester or the person it is for. */
export function WithdrawButton({
  onWithdraw,
  pending,
}: {
  onWithdraw: () => void;
  pending: boolean;
}) {
  const t = useLabel();
  const [asking, setAsking] = useState(false);
  return (
    <>
      <Button
        onClick={() => {
          setAsking(true);
        }}
        data-testid="sr-withdraw"
      >
        {t('requests.withdraw')}
      </Button>
      <Modal
        open={asking}
        title={t('requests.withdraw')}
        okText={t('requests.withdraw')}
        okButtonProps={{ danger: true, loading: pending }}
        cancelText={t('actions.cancel')}
        onOk={() => {
          onWithdraw();
          setAsking(false);
        }}
        onCancel={() => {
          setAsking(false);
        }}
      >
        {t('requests.withdraw_confirm')}
      </Modal>
    </>
  );
}
