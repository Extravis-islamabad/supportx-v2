import { App, Drawer, Flex, List, Typography } from 'antd';

import {
  ApiError,
  useDiscardMail,
  useReleaseMail,
  useWaitingMail,
  type Mailbox,
  type WaitingMail,
} from '@supportx/api-client';
import { markHandled, reportError, useDateTime, useLabel, WriteButton } from '@supportx/ui';

// Reasons this module gives; any other is the record owner's refusal, an error code.
const OWN_REASONS = new Set(['sender_rate', 'not_requester', 'no_target', 'too_large']);

/** A waiting message's reason in words, with its parameters filled. */
function useWaitingReason(): (reason: string | null, params: Record<string, string>) => string {
  const t = useLabel();
  return (reason, params) => {
    const code = reason ?? 'no_target';
    return OWN_REASONS.has(code) ? t(`mail_waiting_reason.${code}`) : t(`errors.${code}`, params);
  };
}

/**
 * The review queue of one mailbox (D-109: held mail is never invisible): who sent each message,
 * about what, and why it waits; hand it in again once the reason is fixed, or discard it. Live:
 * the page's tenant-channel signal refreshes it.
 */
export function WaitingMailDrawer({ mailbox, onClose }: { mailbox: Mailbox; onClose: () => void }) {
  const t = useLabel();
  const dates = useDateTime();
  const { message, modal } = App.useApp();
  const waiting = useWaitingMail(mailbox.id);
  const release = useReleaseMail();
  const discard = useDiscardMail();
  const reasonText = useWaitingReason();

  // Someone else handled it first: say so, the list refreshes.
  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.code === 'mail_not_waiting') {
      markHandled(error);
      void message.info(t('errors.mail_not_waiting'));
      return;
    }
    reportError(error);
  };
  const handIn = (item: WaitingMail) => {
    release.mutate(
      { mailboxId: mailbox.id, messageId: item.message_id },
      {
        onSuccess: (result) => {
          if (result.outcome === 'held') {
            void message.warning(
              t('mail.waiting.still_waiting', {
                reason: reasonText(result.reason, result.reason_params),
              }),
            );
          } else {
            void message.success(
              t('mail.waiting.released', { outcome: t(`mail_outcome.${result.outcome}`) }),
            );
          }
        },
        onError: failed,
      },
    );
  };

  return (
    <Drawer
      open
      width={640}
      title={t('mail.waiting.title', { address: mailbox.address })}
      onClose={onClose}
      destroyOnHidden
      data-testid="mail-waiting"
    >
      <Flex vertical gap={12}>
        <Typography.Text type="secondary">{t('mail.waiting.intro')}</Typography.Text>
        <List<WaitingMail>
          loading={waiting.isPending}
          dataSource={waiting.data ?? []}
          locale={{
            emptyText: <Typography.Text type="secondary">{t('mail.waiting.none')}</Typography.Text>,
          }}
          renderItem={(item) => (
            <List.Item
              data-testid="mail-waiting-item"
              actions={[
                ...(item.releasable
                  ? [
                      <WriteButton
                        key="release"
                        size="small"
                        type="primary"
                        loading={
                          release.isPending && release.variables.messageId === item.message_id
                        }
                        onClick={() => {
                          handIn(item);
                        }}
                        data-testid="mail-waiting-release"
                      >
                        {t('mail.waiting.release')}
                      </WriteButton>,
                    ]
                  : []),
                <WriteButton
                  key="discard"
                  size="small"
                  danger
                  onClick={() => {
                    modal.confirm({
                      title: t('mail.waiting.discard_title'),
                      content: t('mail.waiting.discard_body'),
                      okText: t('mail.waiting.discard'),
                      okButtonProps: { danger: true },
                      cancelText: t('actions.cancel'),
                      onOk: () =>
                        discard
                          .mutateAsync({ mailboxId: mailbox.id, messageId: item.message_id })
                          .catch(failed),
                    });
                  }}
                  data-testid="mail-waiting-discard"
                >
                  {t('mail.waiting.discard')}
                </WriteButton>,
              ]}
            >
              <List.Item.Meta
                title={<Typography.Text strong>{item.subject}</Typography.Text>}
                description={
                  <Flex vertical gap={2}>
                    <Typography.Text type="secondary">
                      {t('mail.waiting.from', {
                        sender: item.sender,
                        when: dates.format(item.received_at),
                      })}
                    </Typography.Text>
                    <Typography.Text data-testid="mail-waiting-reason">
                      {reasonText(item.reason, item.reason_params)}
                    </Typography.Text>
                  </Flex>
                }
              />
            </List.Item>
          )}
        />
      </Flex>
    </Drawer>
  );
}
