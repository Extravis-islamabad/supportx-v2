import { App, Button, Flex, Popconfirm, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  queryKeys,
  useInvitationAction,
  useInvitations,
  useInvite,
  useRequireNewPassword,
  useResetMfa,
  useSession,
  type Invitation,
  type UserDetail,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  FormProblem,
  useAccess,
  useConflict,
  useDateTime,
  useFormProblem,
  useLabel,
} from '@supportx/ui';

import { invitationView, useInvitationFieldName } from './conflict';

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
  const resetMfa = useResetMfa();
  const { can } = useAccess();
  const self = useSession().data?.user.id === user.id;
  const [key, setKey] = useState(() => crypto.randomUUID());
  const queryClient = useQueryClient();
  // A refused action (no email, a rule) is shown here in the person's record (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // The invitation changed by another admin first (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflict();
  const invitationField = useInvitationFieldName();
  const [tried, setTried] = useState<Invitation>();
  useListChannel(notSignedIn ? 'invitations' : null, () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.identity.invitations });
  });
  if (user.status !== 'active' || !user.can_sign_in) return null;
  const onError = (error: unknown) => {
    problem.show(error);
  };

  if (!notSignedIn) {
    return (
      <Flex vertical gap={8} data-testid="person-sign-in-actions">
        <Typography.Text strong>{t('people.sign_in')}</Typography.Text>
        <FormProblem problem={problem} />
        <div>
          <Popconfirm
            title={t('people.require_password_confirm', { name: user.display_name })}
            description={t('people.require_password_explain')}
            okText={t('people.require_password')}
            cancelText={t('actions.cancel')}
            onConfirm={() => {
              problem.clear();
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
        {can('identity.manage') && !self && (
          <div>
            <Popconfirm
              title={t('people.reset_mfa_confirm', { name: user.display_name })}
              description={t('people.reset_mfa_explain')}
              okText={t('people.reset_mfa')}
              cancelText={t('actions.cancel')}
              onConfirm={() => {
                problem.clear();
                resetMfa.mutate(user.id, {
                  onSuccess: () => {
                    void message.success(t('people.reset_mfa_done', { name: user.display_name }));
                  },
                  onError,
                });
              }}
            >
              <Button loading={resetMfa.isPending} data-testid="person-reset-mfa">
                {t('people.reset_mfa')}
              </Button>
            </Popconfirm>
          </div>
        )}
      </Flex>
    );
  }

  const waiting = invitations.data?.items.find(
    (row) => row.status === 'pending' || row.status === 'expired',
  );
  const live = invitations.data?.items.find((row) => row.id === tried?.id);
  const resend = (row: Invitation, version = row.version) => {
    problem.clear();
    act.mutate(
      { id: row.id, version, action: 'resend' },
      {
        onSuccess: () => {
          void message.success(t('security.invitations.resent'));
        },
        onError: (error) => {
          if (conflict.take(error)) {
            setTried(row);
            void invitations.refetch();
            return;
          }
          onError(error);
        },
      },
    );
  };
  return (
    <Flex vertical gap={8} data-testid="person-sign-in-actions">
      <Typography.Text strong>{t('people.sign_in')}</Typography.Text>
      <FormProblem problem={problem} />
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
              problem.clear();
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
              resend(waiting);
            }}
            data-testid="person-invite-again"
          >
            {t('security.invitations.resend')}
          </Button>
        )}
      </div>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={invitationField}
        opened={invitationView(tried)}
        latest={invitationView(live)}
        onReload={() => {
          conflict.clear();
          setTried(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (tried !== undefined) resend(tried, conflict.latestVersion ?? live?.version);
          setTried(undefined);
        }}
      />
    </Flex>
  );
}
