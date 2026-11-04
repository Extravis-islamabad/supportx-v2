import { useQueryClient } from '@tanstack/react-query';
import { Button, Checkbox, Empty, Form, Input, List, Modal, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  serviceRequestKeys,
  useDecideApproval,
  useMyApprovals,
  type PendingApproval,
} from '@supportx/api-client';
import { usePersonalChannel, useTenantChannel } from '@supportx/realtime';
import { lengthLimit, reportError, useDateTime, useLabel } from '@supportx/ui';

const COMMENT_MAX = 4000;
const MY_APPROVALS_CHANGED = 'work_items.my_approvals_changed';

/**
 * Approvals waiting for you, in the portal (WP-030 s2, REQ-PRT-008, REQ-SR-025): a
 * requester-only approver decides here (REQ-SR-022 AC2). Live from your personal channel; a
 * rejection needs a reason, an approval a comment when the item says so (REQ-SR-028).
 */
export function ApprovalsPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const mine = useMyApprovals();
  const decide = useDecideApproval();
  const [open, setOpen] = useState<{ item: PendingApproval; decision: 'approve' | 'reject' }>();
  const [comment, setComment] = useState('');
  const [isPrivate, setPrivate] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const refresh = (type: string) => {
    if (type === MY_APPROVALS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.myApprovals });
    }
  };
  usePersonalChannel((event) => {
    refresh(event.type);
  });
  useTenantChannel((event) => {
    refresh(event.type);
  });
  const items = mine.data?.items ?? [];
  const people = mine.data?.people ?? {};
  const close = () => {
    setOpen(undefined);
    setComment('');
    setPrivate(false);
    setProblems([]);
  };
  const needed = open !== undefined && (open.decision === 'reject' || open.item.comments_required);
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Title level={1}>{t('portal.approvals.title')}</Typography.Title>
      <List
        loading={mine.isLoading}
        dataSource={items}
        data-testid="portal-approvals"
        locale={{ emptyText: <Empty description={t('requests.no_approvals_waiting')} /> }}
        renderItem={(a) => (
          <List.Item key={a.approval_id} data-testid={`portal-approval-${a.display_id}`}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Typography.Text strong>
                <span dir="ltr">{a.display_id}</span> · <bdi>{a.subject}</bdi>
              </Typography.Text>
              <Typography.Text type="secondary">
                {t('requests.for_person', {
                  name: people[a.on_behalf_of_id ?? a.requester_id]?.display_name ?? '',
                })}{' '}
                · {format(a.created_at)}
              </Typography.Text>
              <Space>
                <Button
                  type="primary"
                  onClick={() => {
                    setOpen({ item: a, decision: 'approve' });
                  }}
                >
                  {t('requests.approve')}
                </Button>
                <Button
                  danger
                  onClick={() => {
                    setOpen({ item: a, decision: 'reject' });
                  }}
                >
                  {t('requests.reject')}
                </Button>
              </Space>
            </Space>
          </List.Item>
        )}
      />
      {open !== undefined && (
        <Modal
          open
          title={t(open.decision === 'approve' ? 'requests.approve' : 'requests.reject')}
          okText={t(open.decision === 'approve' ? 'requests.approve' : 'requests.reject')}
          okButtonProps={{
            disabled: needed && comment.trim() === '',
            loading: decide.isPending,
            danger: open.decision === 'reject',
          }}
          cancelText={t('actions.cancel')}
          onCancel={close}
          onOk={() => {
            decide.mutate(
              {
                recordId: open.item.record_id,
                approvalId: open.item.approval_id,
                version: open.item.approval_version,
                body: {
                  decision: open.decision,
                  comment: comment.trim() || null,
                  private: isPrivate,
                },
              },
              {
                onSuccess: close,
                onError: (error) => {
                  if (error instanceof ApiError && error.status === 422) {
                    setProblems(error.fieldErrors.map((f) => t(f.message_key, f.params ?? {})));
                    return;
                  }
                  close();
                  reportError(error);
                },
              },
            );
          }}
        >
          <Form layout="vertical">
            <Form.Item
              label={t(
                open.decision === 'reject' ? 'requests.reject_reason' : 'requests.decision_comment',
              )}
              htmlFor="portal-approval-comment"
              required={needed}
              validateStatus={problems.length > 0 ? 'error' : undefined}
              help={problems.length > 0 ? problems.join(' ') : undefined}
            >
              <Input.TextArea
                id="portal-approval-comment"
                data-testid="portal-approval-comment"
                value={comment}
                count={lengthLimit(COMMENT_MAX)}
                autoSize={{ minRows: 3 }}
                onChange={(e) => {
                  setComment(e.target.value);
                }}
              />
            </Form.Item>
            <Checkbox
              checked={isPrivate}
              onChange={(e) => {
                setPrivate(e.target.checked);
              }}
            >
              {t('requests.private_comment')}
            </Checkbox>
          </Form>
        </Modal>
      )}
    </Space>
  );
}
