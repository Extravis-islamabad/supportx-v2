import { Alert, App, Button, Card, Input, List, Modal, Space, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  ApiError,
  queryKeys,
  useAnswerAcknowledgement,
  useMyAssets,
  type MyAsset,
} from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';
import { EmptyText, lengthLimit, reportError, ToneTag, useDateTime, useLabel } from '@supportx/ui';

import { MyBookings } from './MyBookings';

// Sent on the person's own channel when what they hold, or an acknowledgement, changes.
const MINE_CHANGED = 'assets.mine_changed';
const COMMENT_MAX = 2000;

const TONES = { pending: 'warning', accepted: 'success', disputed: 'error' } as const;

/** Dispute: say what is wrong (the technician who gave it is told). */
function DisputeDialog({ row, onClose }: { row: MyAsset | undefined; onClose: () => void }) {
  const t = useLabel();
  const answer = useAnswerAcknowledgement();
  const [comment, setComment] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const close = () => {
    setComment('');
    setProblem(null);
    onClose();
  };
  return (
    <Modal
      open={row !== undefined}
      title={t('my_assets.dispute_title', { name: row?.name ?? '' })}
      okText={t('my_assets.dispute')}
      cancelText={t('actions.cancel')}
      okButtonProps={{ disabled: comment.trim() === '' }}
      confirmLoading={answer.isPending}
      onCancel={close}
      onOk={() => {
        const ack = row?.acknowledgement;
        if (ack == null) return;
        answer.mutate(
          { id: ack.id, accept: false, comment: comment.trim() },
          {
            onSuccess: close,
            onError: (error) => {
              if (error instanceof ApiError && error.problem !== null) {
                setProblem(t(error.messageKey, error.params));
              } else reportError(error);
            },
          },
        );
      }}
      destroyOnHidden
      data-testid="my-assets-dispute"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Typography.Paragraph type="secondary">{t('my_assets.dispute_help')}</Typography.Paragraph>
      <Input.TextArea
        value={comment}
        onChange={(event) => {
          setComment(event.target.value);
        }}
        rows={4}
        count={lengthLimit(COMMENT_MAX)}
        aria-label={t('my_assets.dispute_comment')}
        data-testid="my-assets-dispute-comment"
      />
    </Modal>
  );
}

/**
 * My assets in the portal (WP-049a s4; REQ-AST-023, 024): what I hold, and my department's when
 * the organisation shows them; I accept or dispute what was given to me. Live: a new asset, or
 * an answer from another device, shows without a refresh. Works without mail (AC4).
 */
export function MyAssetsPage() {
  const t = useLabel();
  const { message } = App.useApp();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const mine = useMyAssets();
  const answer = useAnswerAcknowledgement();
  const [disputing, setDisputing] = useState<MyAsset>();
  usePersonalChannel((event) => {
    if (event.type === MINE_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.mine });
    }
  });
  return (
    <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 840 }}>
      <Typography.Title level={1}>{t('my_assets.title')}</Typography.Title>
      <Card data-testid="my-assets">
        <List
          loading={mine.isPending}
          dataSource={mine.data ?? []}
          locale={{ emptyText: <EmptyText>{t('my_assets.none')}</EmptyText> }}
          renderItem={(row) => {
            const ack = row.acknowledgement;
            return (
              <List.Item
                key={row.id}
                data-testid={`my-asset-${row.id}`}
                actions={
                  ack?.status === 'pending'
                    ? [
                        <Button
                          key="accept"
                          type="primary"
                          loading={answer.isPending && answer.variables.id === ack.id}
                          onClick={() => {
                            answer.mutate(
                              { id: ack.id, accept: true },
                              {
                                onSuccess: () => void message.success(t('my_assets.accepted')),
                                onError: reportError,
                              },
                            );
                          }}
                          data-testid={`my-asset-accept-${row.id}`}
                        >
                          {t('my_assets.accept')}
                        </Button>,
                        <Button
                          key="dispute"
                          onClick={() => {
                            setDisputing(row);
                          }}
                          data-testid={`my-asset-dispute-${row.id}`}
                        >
                          {t('my_assets.dispute')}
                        </Button>,
                      ]
                    : []
                }
              >
                <List.Item.Meta
                  title={
                    <Space wrap>
                      <bdi dir="auto">{row.name}</bdi>
                      {row.tag != null && (
                        <Typography.Text type="secondary">
                          <bdi dir="ltr">{row.tag}</bdi>
                        </Typography.Text>
                      )}
                      {row.through_department && (
                        <ToneTag tone="default">{t('my_assets.department')}</ToneTag>
                      )}
                      {/* On a loan: when it is due back; red once past, live from the overdue notice. */}
                      {row.loan_due_at != null && (
                        <ToneTag
                          tone={row.loan_overdue ? 'error' : 'warning'}
                          testId={`my-asset-due-${row.id}`}
                        >
                          {t('my_assets.due', { date: format(row.loan_due_at) })}
                        </ToneTag>
                      )}
                    </Space>
                  }
                  description={
                    ack == null ? null : (
                      <Space wrap>
                        <ToneTag tone={TONES[ack.status]}>
                          {t(`asset_ack_status.${ack.status}`)}
                        </ToneTag>
                        {ack.answered_at != null && (
                          <Typography.Text type="secondary">
                            {format(ack.answered_at)}
                          </Typography.Text>
                        )}
                      </Space>
                    )
                  }
                />
              </List.Item>
            );
          }}
        />
      </Card>
      {/* WP-049b s1 (REQ-AST-032 AC3): booking ahead, only while the organisation allows it. */}
      <MyBookings />
      <DisputeDialog
        row={disputing}
        onClose={() => {
          setDisputing(undefined);
        }}
      />
    </Space>
  );
}
