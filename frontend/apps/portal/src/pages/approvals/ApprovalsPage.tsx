import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  serviceRequestKeys,
  useApproveMany,
  useDecideApproval,
  useMyApprovals,
  useMyDecidedApprovals,
  useMyTypeApprovals,
  type PendingApproval,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { usePersonalChannel, useTenantChannel } from '@supportx/realtime';
import { lengthLimit, reportError, useDateTime, useLabel } from '@supportx/ui';

const COMMENT_MAX = 4000;
const BULK_MAX = 20; // D-143: approve at most this many at once
const MY_APPROVALS_CHANGED = 'work_items.my_approvals_changed';

/** An approval in the list: a service request's, or a change's (WP-045d S4a). */
type Waiting = PendingApproval & { type: 'service-requests' | 'changes' };

/**
 * Approvals waiting for you, in the portal (WP-030 s2, REQ-PRT-008, REQ-SR-025): a
 * requester-only approver decides here (REQ-SR-022 AC2), a change's too (REQ-CHG-109 AC3). Live
 * from your personal channel; a rejection needs a reason, an approval a comment when the item
 * says so (REQ-SR-028). Bulk approval stays with service requests (D-143).
 */
export function ApprovalsPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const listFormat = useListFormat();
  const mine = useMyApprovals();
  // Optional: without changes on the plan it answers with an error and simply lists none.
  const changes = useMyTypeApprovals('changes');
  const decided = useMyDecidedApprovals();
  const decide = useDecideApproval();
  const approveMany = useApproveMany();
  // Bulk approve (WP-032 D6, REQ-PRT-008 AC1): the ones ticked, confirmed by name, one comment.
  const [picked, setPicked] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [bulkComment, setBulkComment] = useState('');
  const [skipped, setSkipped] = useState<string[]>([]);
  const [open, setOpen] = useState<{ item: Waiting; decision: 'approve' | 'reject' }>();
  const [comment, setComment] = useState('');
  const [isPrivate, setPrivate] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const refresh = (type: string) => {
    if (type === MY_APPROVALS_CHANGED) {
      // A request withdrawn meanwhile leaves the inbox live (AC3).
      void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.myApprovals });
      void queryClient.invalidateQueries({ queryKey: ['changes', 'my-approvals'] });
    }
  };
  usePersonalChannel((event) => {
    refresh(event.type);
  });
  useTenantChannel((event) => {
    refresh(event.type);
  });
  const items: Waiting[] = [
    ...(mine.data?.items ?? []).map((a) => ({ ...a, type: 'service-requests' as const })),
    ...(changes.data?.items ?? []).map((a) => ({ ...a, type: 'changes' as const })),
  ];
  const people = { ...(changes.data?.people ?? {}), ...(mine.data?.people ?? {}) };
  const chosen = items.filter((a) => picked.includes(a.approval_id));
  // Bulk approval never asks a comment an item requires of its own: those are decided one by one.
  const bulkable = items.filter((a) => a.type === 'service-requests' && !a.comments_required);
  const pastItems = decided.data?.items ?? [];
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
      {skipped.length > 0 && (
        <Alert
          type="warning"
          showIcon
          closable
          onClose={() => {
            setSkipped([]);
          }}
          data-testid="portal-approvals-skipped"
          message={t('portal.approvals.skipped', { ids: listFormat(skipped, 'conjunction') })}
        />
      )}
      {bulkable.length > 1 && (
        <Space wrap>
          <Checkbox
            checked={picked.length > 0 && picked.length === Math.min(bulkable.length, BULK_MAX)}
            indeterminate={picked.length > 0 && picked.length < Math.min(bulkable.length, BULK_MAX)}
            onChange={(e) => {
              setPicked(
                e.target.checked ? bulkable.slice(0, BULK_MAX).map((a) => a.approval_id) : [],
              );
            }}
            data-testid="portal-approvals-pick-all"
          >
            {t('portal.approvals.pick_all', { max: BULK_MAX })}
          </Checkbox>
          <Button
            type="primary"
            disabled={picked.length === 0}
            onClick={() => {
              setConfirming(true);
            }}
            data-testid="portal-approvals-approve-picked"
          >
            {t('portal.approvals.approve_picked', { count: picked.length })}
          </Button>
        </Space>
      )}
      <List
        loading={mine.isLoading}
        dataSource={items}
        data-testid="portal-approvals"
        locale={{ emptyText: <Empty description={t('requests.no_approvals_waiting')} /> }}
        renderItem={(a) => (
          <List.Item key={a.approval_id} data-testid={`portal-approval-${a.display_id}`}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Space>
                {bulkable.length > 1 && bulkable.includes(a) && (
                  <Checkbox
                    aria-label={t('portal.approvals.pick', { id: a.display_id })}
                    checked={picked.includes(a.approval_id)}
                    disabled={!picked.includes(a.approval_id) && picked.length >= BULK_MAX}
                    onChange={(e) => {
                      setPicked(
                        e.target.checked
                          ? [...picked, a.approval_id]
                          : picked.filter((id) => id !== a.approval_id),
                      );
                    }}
                    data-testid={`portal-approval-pick-${a.display_id}`}
                  />
                )}
                {/* What is asked opens read-only before deciding (QA10-P2-06); a change's
                    approver decides from its summary here, as the portal shows a change to its
                    requester only. */}
                {a.type === 'service-requests' ? (
                  <Link
                    to={`/service-requests/${a.record_id}`}
                    data-testid={`portal-approval-open-${a.display_id}`}
                  >
                    <Typography.Text strong>
                      <span dir="ltr">{a.display_id}</span> · <bdi>{a.subject}</bdi>
                    </Typography.Text>
                  </Link>
                ) : (
                  <Typography.Text strong>
                    <span dir="ltr">{a.display_id}</span> · <bdi>{a.subject}</bdi>
                  </Typography.Text>
                )}
                {a.type === 'changes' && (
                  <Tag data-testid={`portal-approval-change-${a.display_id}`}>
                    {t('portal.approvals.change')}
                  </Tag>
                )}
                {a.origin === 'backup' && (
                  <Tag data-testid={`portal-approval-delegated-${a.display_id}`}>
                    {t('portal.approvals.delegated')}
                  </Tag>
                )}
              </Space>
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
      {pastItems.length > 0 && (
        <>
          <Typography.Title level={2} style={{ fontSize: 18 }}>
            {t('portal.approvals.decided_title')}
          </Typography.Title>
          <List
            dataSource={pastItems}
            data-testid="portal-approvals-decided"
            renderItem={(a) => (
              <List.Item key={a.approval_id}>
                <Space wrap>
                  <Typography.Text>
                    <span dir="ltr">{a.display_id}</span> · <bdi>{a.subject}</bdi>
                  </Typography.Text>
                  <Tag>{t(`approval_state.${a.state}`)}</Tag>
                  {a.decided_at != null && (
                    <Typography.Text type="secondary">{format(a.decided_at)}</Typography.Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </>
      )}
      {confirming && (
        <Modal
          open
          title={t('portal.approvals.confirm_title', { count: chosen.length })}
          okText={t('portal.approvals.approve_picked', { count: chosen.length })}
          okButtonProps={{ loading: approveMany.isPending }}
          cancelText={t('actions.cancel')}
          onCancel={() => {
            setConfirming(false);
          }}
          onOk={() => {
            approveMany.mutate(
              {
                items: chosen.map((a) => ({
                  record_id: a.record_id,
                  approval_id: a.approval_id,
                  version: a.approval_version,
                })),
                comment: bulkComment.trim() || null,
              },
              {
                onSuccess: (done) => {
                  const byId = new Map(chosen.map((a) => [a.approval_id, a.display_id]));
                  setSkipped(
                    done.items.filter((o) => !o.decided).map((o) => byId.get(o.approval_id) ?? ''),
                  );
                  setConfirming(false);
                  setPicked([]);
                  setBulkComment('');
                },
                onError: (error) => {
                  setConfirming(false);
                  reportError(error);
                },
              },
            );
          }}
        >
          {/* The confirmation names every request (AC1). */}
          <List
            size="small"
            dataSource={chosen}
            data-testid="portal-approvals-confirm-list"
            renderItem={(a) => (
              <List.Item key={a.approval_id}>
                <span dir="ltr">{a.display_id}</span> · <bdi>{a.subject}</bdi>
              </List.Item>
            )}
          />
          <Form layout="vertical" style={{ marginTop: 12 }}>
            <Form.Item label={t('requests.decision_comment')} htmlFor="portal-bulk-comment">
              <Input.TextArea
                id="portal-bulk-comment"
                data-testid="portal-bulk-comment"
                value={bulkComment}
                count={lengthLimit(COMMENT_MAX)}
                autoSize={{ minRows: 2 }}
                onChange={(e) => {
                  setBulkComment(e.target.value);
                }}
              />
            </Form.Item>
          </Form>
        </Modal>
      )}
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
                type: open.item.type,
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
