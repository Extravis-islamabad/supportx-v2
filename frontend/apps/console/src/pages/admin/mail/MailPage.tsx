import { useQueryClient } from '@tanstack/react-query';
import { App, Flex, List, Space, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';

import {
  queryKeys,
  useMailboxes,
  useRemoveMailbox,
  useStartMailboxSignIn,
  useTestMailbox,
  type Mailbox,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  reportError,
  ToneTag,
  useConflictRetry,
  useDateTime,
  useLabel,
  WriteButton,
  type Tone,
} from '@supportx/ui';

import { MailboxEditor } from './MailboxEditor';
import { WaitingMailDrawer } from './WaitingMailDrawer';
import { mailboxView, useMailboxFieldName } from './conflict';
import { browser } from './navigation';

const WARNING_DAYS = 14; // as the server announces it (CREDENTIAL_WARNING_DAYS)
const DAY_MS = 86_400_000;

/** The OAuth app's secret or certificate expires within the warning period (or has expired). */
function expiresSoon(mailbox: Mailbox, now: number): boolean {
  if (mailbox.credential_expires_at == null) return false;
  return Date.parse(mailbox.credential_expires_at) - now < WARNING_DAYS * DAY_MS;
}

const STATE_TONE: Record<Mailbox['state'], Tone> = {
  not_set_up: 'default',
  working: 'success',
  failing: 'error',
};

/**
 * Admin › Mail (WP-024; REQ-ADM-066, REQ-INC-023 AC4): the support mailboxes, whether each is
 * read, why not, and how many messages wait for an admin. A mailbox that cannot be read says so
 * here, not only in logs. Changes by another admin and every fetch that changes something show
 * without a reload (`integrations.mailboxes_changed`).
 */
export function MailPage() {
  const t = useLabel();
  const dates = useDateTime();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const mailboxes = useMailboxes();
  const remove = useRemoveMailbox();
  const test = useTestMailbox();
  const signIn = useStartMailboxSignIn();
  const [params, setParams] = useSearchParams();
  // Back from Microsoft's or Google's sign-in: say how it went once, then clean the address.
  const returned = params.get('sign_in');
  const announced = useRef<string | null>(null);
  useEffect(() => {
    // Once per return, although the effect runs again before the address is cleaned.
    if (returned === null || announced.current === returned) return;
    announced.current = returned;
    if (returned === 'ok') void message.success(t('mail.oauth.signed_in'));
    else
      void message.error(
        t('mail.oauth.sign_in_failed', { reason: t(`mailbox_reason.${returned}`) }),
      );
    setParams({}, { replace: true });
  }, [returned, message, setParams, t]);
  const startSignIn = (mailbox: Mailbox) => {
    signIn.mutate(
      { id: mailbox.id },
      {
        onSuccess: (result) => {
          browser.go(result.authorize_url);
        },
        onError: reportError,
      },
    );
  };
  // When the page opened: expiry is announced days ahead, so a fresh clock per render is not needed.
  const [now] = useState(() => Date.now());
  const retry = useConflictRetry();
  const fieldName = useMailboxFieldName();
  const [editing, setEditing] = useState<Mailbox | 'new' | null>(null);
  const [removing, setRemoving] = useState<Mailbox>();
  const [reviewing, setReviewing] = useState<string | null>(null);
  useTenantChannel((event) => {
    if (event.type === 'integrations.mailboxes_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.mailboxes.all });
    }
  });
  const items = mailboxes.data ?? [];
  const live = (id: string | undefined) => items.find((m) => m.id === id);

  const removeIt = (mailbox: Mailbox, version = mailbox.version) =>
    remove.mutateAsync({ id: mailbox.id, version }).catch((error: unknown) => {
      setRemoving(mailbox);
      if (!retry.take(error, (latest) => void removeIt(mailbox, latest))) reportError(error);
    });
  const testIt = (mailbox: Mailbox) => {
    test.mutate(
      { id: mailbox.id },
      {
        onSuccess: (result) => {
          if (result.ok) void message.success(t('mail.test_passed'));
          else
            void message.error(
              t('mail.test_failed', {
                reason: t(`mailbox_reason.${result.reason ?? 'imap_unreachable'}`),
              }),
            );
        },
        onError: reportError,
      },
    );
  };

  return (
    <Flex vertical gap={16} data-testid="admin-mail">
      <Flex justify="space-between" align="start" gap={12} wrap>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, maxWidth: 720 }}>
          {t('mail.intro')}
        </Typography.Paragraph>
        <WriteButton
          type="primary"
          onClick={() => {
            setEditing('new');
          }}
          data-testid="mailbox-add"
        >
          {t('mail.add')}
        </WriteButton>
      </Flex>
      <List<Mailbox>
        loading={mailboxes.isPending}
        dataSource={items}
        locale={{
          emptyText: <Typography.Text type="secondary">{t('mail.none')}</Typography.Text>,
        }}
        renderItem={(mailbox) => (
          <List.Item
            data-testid={`mailbox-${mailbox.address}`}
            actions={[
              ...(mailbox.needs_sign_in
                ? [
                    <WriteButton
                      key="sign-in"
                      size="small"
                      type={mailbox.signed_in ? 'default' : 'primary'}
                      loading={signIn.isPending && signIn.variables.id === mailbox.id}
                      onClick={() => {
                        startSignIn(mailbox);
                      }}
                      data-testid="mailbox-sign-in"
                    >
                      {t(mailbox.signed_in ? 'mail.oauth.sign_in_again' : 'mail.oauth.sign_in')}
                    </WriteButton>,
                  ]
                : []),
              ...(mailbox.held > 0
                ? [
                    <WriteButton
                      key="review"
                      size="small"
                      type="primary"
                      onClick={() => {
                        setReviewing(mailbox.id);
                      }}
                      data-testid="mailbox-review"
                    >
                      {t('mail.waiting.open')}
                    </WriteButton>,
                  ]
                : []),
              <WriteButton
                key="test"
                size="small"
                loading={test.isPending && test.variables.id === mailbox.id}
                onClick={() => {
                  testIt(mailbox);
                }}
                data-testid="mailbox-test"
              >
                {t('mail.test')}
              </WriteButton>,
              <WriteButton
                key="edit"
                size="small"
                onClick={() => {
                  setEditing(mailbox);
                }}
                data-testid="mailbox-edit"
              >
                {t('actions.edit')}
              </WriteButton>,
              <WriteButton
                key="remove"
                size="small"
                danger
                onClick={() => {
                  modal.confirm({
                    title: t('mail.remove_title', { address: mailbox.address }),
                    content: t('mail.remove_body'),
                    okText: t('actions.delete'),
                    okButtonProps: { danger: true },
                    cancelText: t('actions.cancel'),
                    onOk: () => removeIt(mailbox),
                  });
                }}
                data-testid="mailbox-remove"
              >
                {t('actions.delete')}
              </WriteButton>,
            ]}
          >
            <List.Item.Meta
              title={
                <Space wrap>
                  <Typography.Text strong dir="ltr">
                    {mailbox.address}
                  </Typography.Text>
                  {mailbox.display_name !== null && (
                    <Typography.Text type="secondary">{mailbox.display_name}</Typography.Text>
                  )}
                  <ToneTag tone="default" testId="mailbox-protocol">
                    {t(`mailbox_protocol.${mailbox.protocol}`)}
                  </ToneTag>
                  <ToneTag tone={STATE_TONE[mailbox.state]} testId="mailbox-state">
                    {t(`mailbox_state.${mailbox.state}`)}
                  </ToneTag>
                  {!mailbox.enabled && <ToneTag tone="warning">{t('mail.paused')}</ToneTag>}
                  {mailbox.held > 0 && (
                    <ToneTag tone="warning" testId="mailbox-held">
                      {t('mail.held', { count: mailbox.held })}
                    </ToneTag>
                  )}
                </Space>
              }
              description={
                <Flex vertical gap={2}>
                  {mailbox.flooding && (
                    <Typography.Text type="warning" data-testid="mailbox-flooding">
                      {t('mail.flooding')}
                    </Typography.Text>
                  )}
                  {mailbox.needs_sign_in && !mailbox.signed_in && (
                    <Typography.Text type="warning" data-testid="mailbox-needs-sign-in">
                      {t('mail.oauth.not_signed_in')}
                    </Typography.Text>
                  )}
                  {expiresSoon(mailbox, now) && mailbox.credential_expires_at != null && (
                    <Typography.Text type="warning" data-testid="mailbox-credential-expiry">
                      {t('mail.oauth.credential_expires', {
                        when: dates.format(mailbox.credential_expires_at),
                      })}
                    </Typography.Text>
                  )}
                  {mailbox.state_reason !== null && (
                    <Typography.Text type="danger" data-testid="mailbox-reason">
                      {t(`mailbox_reason.${mailbox.state_reason}`)}
                    </Typography.Text>
                  )}
                  <Typography.Text type="secondary">
                    {t('mail.summary', {
                      creates: t(`mailbox_creates.${mailbox.creates}`),
                      strangers: t(`mailbox_unknown_senders.${mailbox.unknown_senders}`),
                    })}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {mailbox.last_fetch_at == null
                      ? t('mail.never_fetched')
                      : t('mail.last_fetch', { when: dates.format(mailbox.last_fetch_at) })}
                  </Typography.Text>
                </Flex>
              }
            />
          </List.Item>
        )}
      />
      {editing !== null && (
        <MailboxEditor
          mailbox={editing === 'new' ? null : editing}
          latest={editing === 'new' ? undefined : live(editing.id)}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
      {reviewing !== null && live(reviewing) !== undefined && (
        <WaitingMailDrawer
          mailbox={live(reviewing) as Mailbox}
          onClose={() => {
            setReviewing(null);
          }}
        />
      )}
      <ConflictDialog
        {...retry.dialog}
        fieldLabel={fieldName}
        opened={mailboxView(removing)}
        latest={mailboxView(live(removing?.id))}
      />
    </Flex>
  );
}
