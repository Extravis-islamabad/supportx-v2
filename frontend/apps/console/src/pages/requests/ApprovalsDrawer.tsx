import { AuditOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Badge, Button, Drawer, Empty, List, Space, Tooltip, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { serviceRequestKeys, useMyApprovals, useMyTypeApprovals } from '@supportx/api-client';
import { usePersonalChannel, useTenantChannel } from '@supportx/realtime';
import { useDateTime, useLabel, WriteButton } from '@supportx/ui';

import { useDecision } from './useDecision';

const MY_APPROVALS_CHANGED = 'work_items.my_approvals_changed';

/**
 * The approvals drawer in the console header (WP-030 s2, REQ-SR-025): how many approvals wait
 * for you, and each request's summary with Approve / Reject. Live: your personal channel says
 * when one of yours opens or closes; the administrators' approvals signal every screen once
 * (the server returns them only to those who may decide them).
 */
export function ApprovalsDrawer() {
  const t = useLabel();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const mine = useMyApprovals();
  // Problems and releases ask approvals too (QA10-P1-08): listed here, decided on the record.
  const problems = useMyTypeApprovals('problems');
  const releases = useMyTypeApprovals('releases');
  const refresh = (type: string) => {
    if (type === MY_APPROVALS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.myApprovals });
      void queryClient.invalidateQueries({ queryKey: ['problems', 'my-approvals'] });
      void queryClient.invalidateQueries({ queryKey: ['releases', 'my-approvals'] });
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
  const others = [
    ...(problems.data?.items ?? []).map((a) => ({ ...a, path: `/problems/${a.record_id}` })),
    ...(releases.data?.items ?? []).map((a) => ({ ...a, path: `/releases/${a.record_id}` })),
  ];
  const count = items.length + others.length;
  const [deciding, setDeciding] = useState('');
  const { dialog, start } = useDecision(deciding);
  return (
    <>
      <Tooltip title={t('requests.my_approvals_count', { count })}>
        <Badge count={count} size="small" offset={[-4, 4]}>
          <Button
            type="text"
            icon={<AuditOutlined />}
            aria-label={t('requests.my_approvals_count', { count })}
            onClick={() => {
              setOpen(true);
            }}
            data-testid="approvals-drawer-open"
          />
        </Badge>
      </Tooltip>
      <Drawer
        open={open}
        title={t('requests.my_approvals')}
        onClose={() => {
          setOpen(false);
        }}
        data-testid="approvals-drawer"
      >
        <List
          dataSource={items}
          locale={{
            emptyText:
              others.length > 0 ? (
                <></>
              ) : (
                <Empty description={t('requests.no_approvals_waiting')} />
              ),
          }}
          renderItem={(a) => {
            const forId = a.on_behalf_of_id ?? a.requester_id;
            return (
              <List.Item key={a.approval_id} data-testid={`my-approval-${a.display_id}`}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Link
                    to={`/requests/${a.record_id}`}
                    onClick={() => {
                      setOpen(false);
                    }}
                  >
                    <span dir="ltr">{a.display_id}</span> · <bdi>{a.subject}</bdi>
                  </Link>
                  <Typography.Text type="secondary">
                    {t('requests.for_person', { name: people[forId]?.display_name ?? '' })} ·{' '}
                    {format(a.created_at)}
                  </Typography.Text>
                  <Space>
                    <WriteButton
                      type="primary"
                      size="small"
                      onClick={() => {
                        setDeciding(a.record_id);
                        start(
                          {
                            id: a.approval_id,
                            version: a.approval_version,
                            comments_required: a.comments_required,
                          },
                          'approve',
                        );
                      }}
                    >
                      {t('requests.approve')}
                    </WriteButton>
                    <WriteButton
                      size="small"
                      danger
                      onClick={() => {
                        setDeciding(a.record_id);
                        start(
                          {
                            id: a.approval_id,
                            version: a.approval_version,
                            comments_required: a.comments_required,
                          },
                          'reject',
                        );
                      }}
                    >
                      {t('requests.reject')}
                    </WriteButton>
                  </Space>
                </Space>
              </List.Item>
            );
          }}
        />
        {others.length > 0 && (
          <List
            dataSource={others}
            data-testid="my-approvals-other"
            renderItem={(a) => (
              <List.Item key={a.approval_id} data-testid={`my-approval-${a.display_id}`}>
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Link
                    to={a.path}
                    onClick={() => {
                      setOpen(false);
                    }}
                  >
                    <span dir="ltr">{a.display_id}</span> · <bdi>{a.subject}</bdi>
                  </Link>
                  <Typography.Text type="secondary">
                    {t('requests.open_to_decide')} · {format(a.created_at)}
                  </Typography.Text>
                </Space>
              </List.Item>
            )}
          />
        )}
      </Drawer>
      {dialog}
    </>
  );
}
