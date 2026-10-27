import { App, Button, Flex, Popconfirm, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  ApiError,
  queryKeys,
  useInvitationAction,
  useInvitations,
  useInvite,
  useRequireNewPassword,
  type UserDetail,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { reportError, useDateTime, useLabel } from '@supportx/ui';

/**
 * Sign-in actions on a person's record (WP-039 session 2, lane B; shown in WP-021's person
 * drawer): invite someone who has not signed in yet (REQ-SEC-018), send a waiting invitation
 * again, or require a new password at the next sign-in (REQ-SEC-006).
 */
export function PersonSignInActions({ user }: { user: UserDetail }) {
  const t = useLabel();
  const { message } = App.useApp();
  const dates = useDateTime();
  const notSignedIn = !user.signed_in_before;
  const invitations = useInvitations(user.id, notSignedIn);
  const invite = useInvite();
  const act = useInvitationAction();
  const requireNew = useRequireNewPassword();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const queryClient = useQueryClient();
  useListChannel(notSignedIn ? 'invitations' : null, () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.identity.invitations });
  });
  if (user.status !== 'active' || !user.can_sign_in) return null;
  const onError = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) void invitations.refetch();
    reportError(error);
  };

  if (!notSignedIn) {
    return (
      <Flex vertical gap={8} data-testid="person-sign-in-actions">
        <Typography.Text strong>{t('people.sign_in')}</Typography.Text>
        <div>
          <Popconfirm
            title={t('people.require_password_confirm', { name: user.display_name })}
            description={t('people.require_password_explain')}
            okText={t('people.require_password')}
            cancelText={t('actions.cancel')}
            onConfirm={() => {
              requireNew.mutate(user.id, {
                onSuccess: () => {
                  void message.success(
                    t('people.require_password_done', { name: user.display_name }),
                  );
                },
                onError,
              });
            }}
          >
            <Button loading={requireNew.isPending} data-testid="person-require-password">
              {t('people.require_password')}
            </Button>
          </Popconfirm>
        </div>
      </Flex>
    );
  }

  const waiting = invitations.data?.items.find(
    (row) => row.status === 'pending' || row.status === 'expired',
  );
  return (
    <Flex vertical gap={8} data-testid="person-sign-in-actions">
      <Typography.Text strong>{t('people.sign_in')}</Typography.Text>
      {waiting !== undefined && (
        <Typography.Text type={waiting.status === 'expired' ? 'warning' : 'secondary'}>
          {waiting.status === 'expired'
            ? t('people.invitation_expired')
            : t('people.invited_until', { date: dates.format(waiting.expires_at) })}
        </Typography.Text>
      )}
      <div>
        {waiting === undefined ? (
          <Button
            type="primary"
            loading={invite.isPending}
            disabled={invitations.isLoading}
            onClick={() => {
              invite.mutate(
                { userId: user.id, key },
                {
                  onSuccess: (sent) => {
                    setKey(crypto.randomUUID());
                    void message.success(
                      t(
                        sent.delivery === 'existing_account'
                          ? 'people.invite_existing'
                          : 'people.invite_sent',
                        { email: sent.email },
                      ),
                    );
                  },
                  onError,
                },
              );
            }}
            data-testid="person-invite"
          >
            {t('people.invite')}
          </Button>
        ) : (
          <Button
            loading={act.isPending}
            onClick={() => {
              act.mutate(
                { id: waiting.id, version: waiting.version, action: 'resend' },
                {
                  onSuccess: () => {
                    void message.success(t('security.invitations.resent'));
                  },
                  onError,
                },
              );
            }}
            data-testid="person-invite-again"
          >
            {t('security.invitations.resend')}
          </Button>
        )}
      </div>
    </Flex>
  );
}
