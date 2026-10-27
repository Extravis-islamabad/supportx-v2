import { App, Button, Card, Flex, InputNumber, Popconfirm, Space, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIdentitySettings,
  useInvitationAction,
  useInvitations,
  useSaveIdentitySettings,
  type Invitation,
} from '@supportx/api-client';
import { reportError, ToneTag, useDateTime, useLabel, WriteButton, type Tone } from '@supportx/ui';

import { FieldNote } from './FieldNote';

const MIN_DAYS = 1;
const MAX_DAYS = 30; // Appendix A: 7 days by default, at most 30 (REQ-SEC-020)

const STATUS_TONE: Record<Invitation['status'], Tone> = {
  pending: 'info',
  accepted: 'success',
  expired: 'warning',
  revoked: 'default',
};

/** How long a new invitation's link works (REQ-SEC-020); saved with the sign-in settings. */
function ValidDays() {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useIdentitySettings();
  const save = useSaveIdentitySettings();
  const [edited, setEdited] = useState<number | null | undefined>(undefined);
  const [refused, setRefused] = useState<string | null>(null);
  if (settings.data === undefined) return null;
  const { version, invitation_valid_days: savedDays } = settings.data;
  const days = edited === undefined ? savedDays : edited;
  const bad = days === null || !Number.isInteger(days) || days < MIN_DAYS || days > MAX_DAYS;
  const problem = bad
    ? t('errors.field.invitation_days_out_of_range', { min: MIN_DAYS, max: MAX_DAYS })
    : refused;
  return (
    <Space wrap align="end" size={12}>
      <FieldNote id="security-invitation-days" message={problem}>
        <label htmlFor="security-invitation-days">{t('security.invitations.valid_days')}</label>
        <InputNumber
          id="security-invitation-days"
          value={days}
          onChange={(value) => {
            setEdited(value);
            setRefused(null);
          }}
          suffix={t('security.password.days')}
          style={{ width: 168 }}
          status={problem === null ? undefined : 'error'}
          aria-describedby="security-invitation-days-problem"
          data-testid="security-invitation-days"
        />
      </FieldNote>
      <WriteButton
        loading={save.isPending}
        disabled={bad || edited === undefined || days === savedDays}
        onClick={() => {
          save.mutate(
            { body: { invitation_valid_days: days ?? 0 }, version },
            {
              onSuccess: () => {
                setEdited(undefined);
                void message.success(t('security.invitations.saved'));
              },
              onError: (error) => {
                const field = error instanceof ApiError ? error.fieldErrors[0] : undefined;
                if (field !== undefined) {
                  setRefused(t(field.message_key, field.params ?? {}));
                  return;
                }
                if (error instanceof ApiError && error.isConflict) {
                  // Another admin saved first: keep what was typed, take their version (D-103 (4)).
                  void settings.refetch();
                  void message.warning(t('security.changed_elsewhere'));
                  return;
                }
                reportError(error);
              },
            },
          );
        }}
        data-testid="security-invitation-days-save"
      >
        {t('actions.save')}
      </WriteButton>
    </Space>
  );
}

/**
 * Invitations (WP-039 session 2; REQ-SEC-018..020): who was invited, until when, and what became
 * of it; send again or withdraw. People are invited from their record (Admin › People).
 */
export function InvitationsCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const dates = useDateTime();
  const invitations = useInvitations();
  const act = useInvitationAction();
  const run = (row: Invitation, action: 'resend' | 'revoke') => {
    act.mutate(
      { id: row.id, version: row.version, action },
      {
        onSuccess: () => {
          void message.success(
            t(action === 'resend' ? 'security.invitations.resent' : 'security.invitations.revoked'),
          );
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) void invitations.refetch();
          reportError(error);
        },
      },
    );
  };
  const waiting = (row: Invitation) => row.status === 'pending' || row.status === 'expired';
  return (
    <Card title={t('security.invitations.title')} data-testid="security-invitations">
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.invitations.intro')}
        </Typography.Paragraph>
        <ValidDays />
        <Table<Invitation>
          rowKey="id"
          size="small"
          loading={invitations.isLoading}
          dataSource={invitations.data?.items ?? []}
          pagination={false}
          scroll={{ x: true }}
          locale={{ emptyText: t('security.invitations.none') }}
          data-testid="security-invitations-list"
          columns={[
            { key: 'email', title: t('security.invitations.person'), dataIndex: 'email' },
            {
              key: 'status',
              title: t('security.invitations.status'),
              render: (_, row) => (
                <ToneTag tone={STATUS_TONE[row.status]} testId="invitation-status">
                  {t(`invitation_status.${row.status}`)}
                </ToneTag>
              ),
            },
            {
              key: 'sent',
              title: t('security.invitations.sent'),
              render: (_, row) => dates.format(row.sent_at),
            },
            {
              key: 'expires',
              title: t('security.invitations.expires'),
              render: (_, row) =>
                row.delivery === 'existing_account'
                  ? t('invitation_delivery.existing_account')
                  : dates.format(row.expires_at),
            },
            {
              key: 'actions',
              title: '',
              render: (_, row) =>
                waiting(row) && (
                  <Space>
                    <Button
                      size="small"
                      disabled={act.isPending}
                      onClick={() => {
                        run(row, 'resend');
                      }}
                      data-testid="invitation-resend"
                    >
                      {t('security.invitations.resend')}
                    </Button>
                    <Popconfirm
                      title={t('security.invitations.revoke_confirm', { email: row.email })}
                      okText={t('security.invitations.revoke')}
                      cancelText={t('actions.cancel')}
                      onConfirm={() => {
                        run(row, 'revoke');
                      }}
                    >
                      <Button size="small" danger data-testid="invitation-revoke">
                        {t('security.invitations.revoke')}
                      </Button>
                    </Popconfirm>
                  </Space>
                ),
            },
          ]}
        />
      </Flex>
    </Card>
  );
}
