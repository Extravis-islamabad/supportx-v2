import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Descriptions, Flex, List, Result, Skeleton, Tag, Typography } from 'antd';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  portalChangeKeys,
  usePortalChange,
  usePortalChangeConversation,
  usePortalChangeReply,
} from '@supportx/api-client';
import { useRecordEvents } from '@supportx/realtime';
import {
  EmptyText,
  reportError,
  RichTextField,
  RichTextView,
  useDateTime,
  useLabel,
} from '@supportx/ui';

/**
 * One change as its requester sees it (WP-045d S4a, REQ-CHG-109): its stage and status, the
 * planned window, the public conversation and a reply box; never its plans, risk, approvals
 * detail or private notes (AC2), which the portal API does not even return. Live on the
 * requester channel (`portal_wi`): it says only that something they may see changed, and the
 * page refetches through the portal API.
 */
export function ChangePage() {
  const t = useLabel();
  const { id = '' } = useParams();
  const queryClient = useQueryClient();
  const { format, relative } = useDateTime();
  const record = usePortalChange(id);
  const conversation = usePortalChangeConversation(id);
  const reply = usePortalChangeReply(id);
  const [draft, setDraft] = useState('');

  useRecordEvents('portal_wi', id, (event) => {
    if (event.type === 'work_items.portal_conversation_changed') {
      void queryClient.invalidateQueries({ queryKey: portalChangeKeys.conversation(id) });
      return;
    }
    void queryClient.invalidateQueries({ queryKey: portalChangeKeys.detail(id) });
  });

  if (record.isLoading) return <Skeleton active />;
  if (record.error || record.data === undefined) {
    return (
      <Result
        status="404"
        title={t('portal.changes.not_found')}
        extra={<Link to="/changes">{t('portal.changes.title')}</Link>}
      />
    );
  }
  const item = record.data;
  const own = item.reach === 'own';
  const closed = item.status_category === 'closed' || item.status_category === 'canceled';
  const entries = conversation.data?.items ?? [];
  const when = (at: string) => <time dateTime={at}>{format(at)}</time>;

  return (
    <Flex vertical gap={16}>
      <Link to="/changes">{t('portal.changes.back')}</Link>
      <Flex vertical gap={4}>
        <Typography.Text type="secondary" dir="ltr" data-testid="portal-change-id">
          {item.display_id}
        </Typography.Text>
        <Typography.Title level={1} style={{ margin: 0, overflowWrap: 'anywhere' }}>
          {item.subject}
        </Typography.Title>
        <Typography.Text type="secondary">
          <time dateTime={item.created_at} title={format(item.created_at)}>
            {t('portal.changes.raised', { when: relative(item.created_at) })}
          </time>
        </Typography.Text>
      </Flex>

      <Card data-testid="portal-change-where">
        <Descriptions size="small" column={1}>
          <Descriptions.Item label={t('work_item.field.stage')}>
            {item.stage != null ? (
              <Tag data-testid="portal-change-stage">{t(`work_item_stage.${item.stage}`)}</Tag>
            ) : (
              <EmptyText>{t('portal.changes.no_stage')}</EmptyText>
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('work_item.field.status')}>
            <Tag color="blue" data-testid="portal-change-status">
              {t(`work_item_status.${item.status}`)}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('portal.changes.planned')}>
            <span data-testid="portal-change-planned">
              {item.planned_start != null && item.planned_end != null ? (
                <>
                  {when(item.planned_start)} – {when(item.planned_end)}
                </>
              ) : item.planned_start != null ? (
                when(item.planned_start)
              ) : (
                <EmptyText>{t('portal.changes.not_planned')}</EmptyText>
              )}
            </span>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <section aria-labelledby="portal-change-conversation">
        <Typography.Title level={2} id="portal-change-conversation">
          {t('portal.conversation.title')}
        </Typography.Title>
        <List
          loading={conversation.isLoading}
          dataSource={entries}
          locale={{ emptyText: <EmptyText>{t('portal.conversation.empty')}</EmptyText> }}
          data-testid="portal-change-conversation"
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
        {own && !closed && (
          <Flex vertical gap={8} style={{ marginTop: 12 }}>
            <RichTextField
              value={draft}
              onChange={setDraft}
              label={t('portal.conversation.reply')}
              placeholder={t('portal.conversation.reply')}
              testId="portal-change-reply"
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
              data-testid="portal-change-reply-send"
            >
              {t('portal.conversation.send')}
            </Button>
          </Flex>
        )}
      </section>
    </Flex>
  );
}
