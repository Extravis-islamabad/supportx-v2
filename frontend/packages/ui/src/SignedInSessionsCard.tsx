import { App, Button, Card, List, Space, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';

import {
  queryKeys,
  useEndMySession,
  useEndPersonSession,
  useMySessions,
  usePersonSessions,
  type ListedSession,
} from '@supportx/api-client';
import { usePersonalChannel } from '@supportx/realtime';

import { useLabel } from './appearance';
import { useDateTime } from './dates';
import { EmptyText } from './EmptyText';
import { reportError } from './errors';
import { ToneTag } from './ToneTag';

// On the person's own channel when their session list changed (identity_access, ADR-044 item 5).
export const SESSIONS_CHANGED = 'identity_access.sessions_changed';

function SessionList({
  rows,
  loading,
  onEnd,
  ending,
}: {
  rows: ListedSession[];
  loading: boolean;
  onEnd: (row: ListedSession) => void;
  ending: string | undefined;
}) {
  const t = useLabel();
  const dates = useDateTime();
  return (
    <List
      size="small"
      loading={loading}
      dataSource={rows}
      locale={{ emptyText: <EmptyText>{t('account.sessions.none')}</EmptyText> }}
      data-testid="signed-in-sessions"
      renderItem={(row) => (
        <List.Item
          data-testid={`session-${row.id}`}
          actions={
            row.current
              ? []
              : [
                  <Button
                    key="end"
                    size="small"
                    danger
                    loading={ending === row.id}
                    onClick={() => {
                      onEnd(row);
                    }}
                    data-testid={`session-end-${row.id}`}
                  >
                    {t('account.sessions.end')}
                  </Button>,
                ]
          }
        >
          <Space direction="vertical" size={2}>
            <Space wrap>
              <Typography.Text strong>
                {row.platform === null
                  ? t(`session_client.${row.client}`)
                  : t('account.sessions.app_on', {
                      platform: t(`session_platform.${row.platform}`),
                    })}
              </Typography.Text>
              {row.app_version !== null && (
                <Typography.Text type="secondary">
                  {t('account.sessions.version', { version: row.app_version })}
                </Typography.Text>
              )}
              {row.current && <ToneTag tone="success">{t('account.sessions.this_device')}</ToneTag>}
            </Space>
            <Typography.Text type="secondary">
              {t('account.sessions.when', {
                started: row.started_at === null ? '' : dates.format(row.started_at),
                used: row.last_used_at === null ? '' : dates.relative(row.last_used_at),
              })}
            </Typography.Text>
          </Space>
        </List.Item>
      )}
    />
  );
}

/** Ask, then end; the list refreshes from the answer and from the live signal. */
function useEnd(end: (id: string) => Promise<unknown>, pending: boolean) {
  const t = useLabel();
  const { modal, message } = App.useApp();
  return {
    ask: (row: ListedSession) => {
      modal.confirm({
        title: t('account.sessions.end_title'),
        content: t('account.sessions.end_body'),
        okText: t('account.sessions.end'),
        okButtonProps: { danger: true },
        cancelText: t('actions.cancel'),
        onOk: async () => {
          try {
            await end(row.id);
            void message.success(t('account.sessions.ended'));
          } catch (error) {
            reportError(error);
          }
        },
      });
    },
    pending,
  };
}

/**
 * My account: every browser and device signed in to this organisation (ADR-044 item 5), this
 * one marked; any other can be signed out at once. Live: a sign-in or sign-out anywhere
 * refreshes the list (the person's own channel).
 */
export function SignedInSessionsCard() {
  const t = useLabel();
  const sessions = useMySessions();
  const end = useEndMySession();
  const queryClient = useQueryClient();
  usePersonalChannel((event) => {
    if (event.type === SESSIONS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.identity.mySessions });
    }
  });
  const { ask } = useEnd(end.mutateAsync, end.isPending);
  return (
    <Card title={t('account.sessions.title')} data-testid="account-sessions">
      <Typography.Paragraph type="secondary">{t('account.sessions.help')}</Typography.Paragraph>
      <SessionList
        rows={sessions.data ?? []}
        loading={sessions.isPending}
        onEnd={ask}
        ending={end.isPending ? end.variables : undefined}
      />
    </Card>
  );
}

/** A person's signed-in browsers and devices, for people admins (a lost phone). */
export function PersonSessions({ userId }: { userId: string }) {
  const sessions = usePersonSessions(userId);
  const end = useEndPersonSession(userId);
  const { ask } = useEnd(end.mutateAsync, end.isPending);
  return (
    <SessionList
      rows={sessions.data ?? []}
      loading={sessions.isPending}
      onEnd={ask}
      ending={end.isPending ? end.variables : undefined}
    />
  );
}
