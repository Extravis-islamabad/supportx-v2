import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Flex, Input, List, Result, Skeleton, Space, Typography } from 'antd';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  portalKeys,
  queryKeys,
  useAnswerFix,
  usePortalConversation,
  usePortalIncident,
  usePortalReply,
  useRecordFiles,
} from '@supportx/api-client';
import { useRecordEvents } from '@supportx/realtime';
import {
  Attachments,
  EmptyText,
  lengthLimit,
  reportError,
  RichTextField,
  RichTextView,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { PortalStatusTag } from './PortalStatusTag';

const COMMENT_MAX = 200_000;

/**
 * One incident as its requester sees it (REQ-INC-147): the plain status, what they wrote, the
 * fix to confirm or reject, the public conversation and a reply box. Live with no reload: the
 * requester channel (`portal_wi`, D4) says only that something they may see changed, and the
 * screen refetches through the portal API.
 */
export function RequestPage() {
  const t = useLabel();
  const { id = '' } = useParams();
  const queryClient = useQueryClient();
  const { format, relative } = useDateTime();
  const record = usePortalIncident(id);
  const conversation = usePortalConversation(id);
  const recordFiles = useRecordFiles('incident', id === '' ? undefined : id);
  const reply = usePortalReply(id);
  const answer = useAnswerFix(id);
  const [draft, setDraft] = useState('');
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState('');

  useRecordEvents('portal_wi', id, (event) => {
    if (event.type === 'work_items.portal_conversation_changed') {
      void queryClient.invalidateQueries({ queryKey: portalKeys.conversation(id) });
      return;
    }
    void queryClient.invalidateQueries({ queryKey: portalKeys.detail(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.files.record('incident', id) });
  });

  if (record.isLoading) return <Skeleton active />;
  if (record.error || record.data === undefined) {
    return (
      <Result
        status="404"
        title={t('portal.request.not_found')}
        extra={<Link to="/requests">{t('nav.my_requests')}</Link>}
      />
    );
  }
  const item = record.data;
  const own = item.reach === 'own';
  const entries = conversation.data?.items ?? [];
  const files = (recordFiles.data ?? []).filter((f) => f.owner_type === 'work_item' && !f.inline);
  // Their own open record only: a manager with wider reach reads; closed records take no files.
  const canAttach = own && !['closed', 'canceled'].includes(item.portal_status);

  return (
    <Flex vertical gap={16}>
      <Link to="/requests">{t('portal.request.back')}</Link>
      <Flex vertical gap={4}>
        <Typography.Text type="secondary" dir="ltr" data-testid="portal-request-id">
          {item.display_id}
        </Typography.Text>
        <Typography.Title level={1} style={{ margin: 0, overflowWrap: 'anywhere' }}>
          {item.subject}
        </Typography.Title>
        <Space wrap>
          <PortalStatusTag status={item.portal_status} />
          <Typography.Text type="secondary">
            <time dateTime={item.created_at} title={format(item.created_at)}>
              {t('portal.request.reported', { when: relative(item.created_at) })}
            </time>
          </Typography.Text>
          {item.resolution_due_at != null && (
            <Typography.Text type="secondary" data-testid="portal-due">
              <time dateTime={item.resolution_due_at} title={format(item.resolution_due_at)}>
                {t('portal.request.expected', { when: format(item.resolution_due_at) })}
              </time>
            </Typography.Text>
          )}
        </Space>
      </Flex>

      {item.portal_status === 'resolved' && own && (
        <Card data-testid="portal-fix">
          <Typography.Title level={2} style={{ marginTop: 0 }}>
            {t('portal.fix.title')}
          </Typography.Title>
          <RichTextView html={item.resolution ?? null} testId="portal-fix-text" />
          {rejecting ? (
            <Flex vertical gap={8} style={{ marginTop: 12 }}>
              <Input.TextArea
                value={comment}
                count={lengthLimit(COMMENT_MAX)}
                autoSize={{ minRows: 3 }}
                onChange={(event) => {
                  setComment(event.target.value);
                }}
                aria-label={t('portal.fix.why')}
                placeholder={t('portal.fix.why')}
                data-testid="portal-fix-comment"
              />
              <Space wrap>
                <Button
                  type="primary"
                  size="large"
                  disabled={comment.trim() === ''}
                  loading={answer.isPending}
                  onClick={() => {
                    answer.mutate(comment.trim(), {
                      onSuccess: () => {
                        setRejecting(false);
                        setComment('');
                      },
                      onError: reportError,
                    });
                  }}
                  data-testid="portal-fix-reject-send"
                >
                  {t('portal.fix.reject_send')}
                </Button>
                <Button
                  size="large"
                  onClick={() => {
                    setRejecting(false);
                  }}
                >
                  {t('actions.cancel')}
                </Button>
              </Space>
            </Flex>
          ) : (
            <Space wrap style={{ marginTop: 12 }}>
              <Button
                type="primary"
                size="large"
                loading={answer.isPending}
                onClick={() => {
                  answer.mutate(null, { onError: reportError });
                }}
                data-testid="portal-fix-confirm"
              >
                {t('portal.fix.confirm')}
              </Button>
              <Button
                size="large"
                onClick={() => {
                  setRejecting(true);
                }}
                data-testid="portal-fix-reject"
              >
                {t('portal.fix.reject')}
              </Button>
            </Space>
          )}
        </Card>
      )}
      {item.portal_status === 'waiting_for_you' && own && (
        <Alert type="warning" showIcon message={t('portal.request.waiting_for_you')} />
      )}

      {item.description !== undefined && (
        <section aria-labelledby="portal-description">
          <Typography.Title level={2} id="portal-description">
            {t('portal.request.description')}
          </Typography.Title>
          {item.description ? (
            <RichTextView html={item.description} testId="portal-description" />
          ) : (
            <EmptyText>{t('portal.request.no_description')}</EmptyText>
          )}
        </section>
      )}

      <section aria-labelledby="portal-files">
        <Typography.Title level={2} id="portal-files">
          {t('files.title')}
        </Typography.Title>
        {files.length === 0 && !canAttach && <EmptyText>{t('files.empty')}</EmptyText>}
        <Attachments
          files={files}
          target={canAttach ? { ownerType: 'work_item', ownerId: item.id } : null}
          onStored={() => {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.files.record('incident', item.id),
            });
          }}
          camera
          testId="portal-files"
        />
      </section>

      <section aria-labelledby="portal-conversation">
        <Typography.Title level={2} id="portal-conversation">
          {t('portal.conversation.title')}
        </Typography.Title>
        <List
          loading={conversation.isLoading}
          dataSource={entries}
          locale={{ emptyText: <EmptyText>{t('portal.conversation.empty')}</EmptyText> }}
          data-testid="portal-conversation"
          renderItem={(entry) => (
            <List.Item key={entry.id} style={{ display: 'block', paddingInline: 0 }}>
              <Typography.Text strong>
                {entry.by_you
                  ? t('portal.conversation.you')
                  : (entry.author_name ?? t('portal.conversation.service_desk'))}
              </Typography.Text>{' '}
              <Typography.Text type="secondary">
                <time dateTime={entry.created_at} title={format(entry.created_at)}>
                  {relative(entry.created_at)}
                </time>
              </Typography.Text>
              <RichTextView html={entry.body} />
            </List.Item>
          )}
        />
        {own && item.portal_status !== 'canceled' && (
          <Flex vertical gap={8} style={{ marginTop: 12 }}>
            <RichTextField
              value={draft}
              onChange={setDraft}
              label={t('portal.conversation.reply')}
              placeholder={t('portal.conversation.reply')}
              testId="portal-reply"
            />
            <Button
              type="primary"
              size="large"
              style={{ alignSelf: 'flex-start' }}
              disabled={draft.replace(/<[^>]*>/g, '').trim() === ''}
              loading={reply.isPending}
              onClick={() => {
                reply.mutate(draft, {
                  onSuccess: () => {
                    setDraft('');
                  },
                  onError: reportError,
                });
              }}
              data-testid="portal-reply-send"
            >
              {t('portal.conversation.send')}
            </Button>
          </Flex>
        )}
      </section>
    </Flex>
  );
}
