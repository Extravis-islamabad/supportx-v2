import { Button, Flex, List, Typography } from 'antd';
import { useState } from 'react';

import { usePortalRequestConversation, usePortalRequestReply } from '@supportx/api-client';
import {
  EmptyText,
  reportError,
  RichTextField,
  RichTextView,
  useDateTime,
  useLabel,
} from '@supportx/ui';

/**
 * A request's public conversation in the portal, with a reply box on one's own open request
 * (WP-047a S3a; REQ-SR-037 AC1-AC2): an approver's question shows here, and the reply answers
 * it. Public replies and notes only; the portal API never returns private notes.
 */
export function RequestConversation({
  id,
  canReply,
}: {
  id: string;
  /** The requester's own request, still open. */
  canReply: boolean;
}) {
  const t = useLabel();
  const { format, relative } = useDateTime();
  const conversation = usePortalRequestConversation(id);
  const reply = usePortalRequestReply(id);
  const [draft, setDraft] = useState('');
  const entries = conversation.data?.items ?? [];
  return (
    <section aria-labelledby="portal-request-conversation">
      <Typography.Title level={2} id="portal-request-conversation">
        {t('portal.conversation.title')}
      </Typography.Title>
      <List
        loading={conversation.isLoading}
        dataSource={entries}
        locale={{ emptyText: <EmptyText>{t('portal.conversation.empty')}</EmptyText> }}
        data-testid="portal-request-conversation"
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
      {canReply && (
        <Flex vertical gap={8} style={{ marginTop: 12 }}>
          <RichTextField
            value={draft}
            onChange={setDraft}
            label={t('portal.conversation.reply')}
            placeholder={t('portal.conversation.reply')}
            testId="portal-request-reply"
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
            data-testid="portal-request-reply-send"
          >
            {t('portal.conversation.send')}
          </Button>
        </Flex>
      )}
    </section>
  );
}
