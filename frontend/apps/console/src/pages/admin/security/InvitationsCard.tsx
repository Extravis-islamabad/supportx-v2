import { App, Button, Card, Flex, InputNumber, Popconfirm, Space, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  type IdentitySettings,
  useIdentitySettings,
  useInvitationAction,
  useInvitations,
  useSaveIdentitySettings,
  type Invitation,
} from '@supportx/api-client';
import {
  ConflictDialog,
  EmptyText,
  FormProblem,
  markHandled,
  reportError,
  ToneTag,
  useConflict,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
  type Tone,
} from '@supportx/ui';

import { editable, invitationView, useInvitationFieldName, useSettingName } from './conflict';
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
  // A refused save with no field to point at is shown here, not as a toast (QA WP-029 BUG-02).
  const formProblem = useFormProblem();
  // A save another admin made first (409): who, when and what, in the shared dialog (BUG-05).
  const conflict = useConflict();
  const settingName = useSettingName();
  // The settings when the edit began: the dialog compares them with the live ones.
  const [base, setBase] = useState<IdentitySettings>();
  if (settings.data === undefined) return null;
  const current = settings.data;
  const { version, invitation_valid_days: savedDays } = settings.data;
  const days = edited === undefined ? savedDays : edited;
  const bad = days === null || !Number.isInteger(days) || days < MIN_DAYS || days > MAX_DAYS;
  const problem = bad
    ? t('errors.field.invitation_days_out_of_range', { min: MIN_DAYS, max: MAX_DAYS })
    : refused;
  const submit = (at: number) => {
    formProblem.clear();
    save.mutate(
      { body: { invitation_valid_days: days ?? 0 }, version: at },
      {
        onSuccess: () => {
          setEdited(undefined);
          void message.success(t('security.invitations.saved'));
        },
        onError: (error) => {
          const field = error instanceof ApiError ? error.fieldErrors[0] : undefined;
          if (field !== undefined) {
            markHandled(error);
            setRefused(t(field.message_key, field.params ?? {}));
            return;
          }
          if (conflict.take(error)) {
            // Another admin saved first: fetch their version; the dialog asks (D-103 (4)).
            void settings.refetch();
            return;
          }
          formProblem.show(error);
        },
      },
    );
  };
  return (
    <div>
      <FormProblem problem={formProblem} />
      <Space wrap align="end" size={12}>
        <FieldNote id="security-invitation-days" message={problem}>
          <label htmlFor="security-invitation-days">{t('security.invitations.valid_days')}</label>
          <InputNumber
            id="security-invitation-days"
            value={days}
            onChange={(value) => {
              if (edited === undefined) setBase(current);
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
            submit(version);
          }}
          data-testid="security-invitation-days-save"
        >
          {t('actions.save')}
        </WriteButton>
      </Space>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={settingName}
        opened={editable(base)}
        latest={editable(current)}
        onReload={() => {
          conflict.clear();
          setEdited(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          setBase(current);
          submit(conflict.latestVersion ?? version);
        }}
      />
    </div>
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
  // An invitation another admin changed first (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflict();
  const invitationField = useInvitationFieldName();
  const [tried, setTried] = useState<{ row: Invitation; action: 'resend' | 'revoke' }>();
  const live = invitations.data?.items.find((row) => row.id === tried?.row.id);
  const run = (row: Invitation, action: 'resend' | 'revoke', version = row.version) => {
    act.mutate(
      { id: row.id, version, action },
      {
        onSuccess: (saved) => {
          if (action === 'resend' && saved.earlier_links_work) {
            // Keycloak cannot withdraw one link: say so rather than imply it (product owner).
            void message.warning(t('security.invitations.resent_earlier_work'));
            return;
          }
          void message.success(
            t(action === 'resend' ? 'security.invitations.resent' : 'security.invitations.revoked'),
          );
        },
        onError: (error) => {
          if (conflict.take(error)) {
            setTried({ row, action });
            void invitations.refetch();
            return;
          }
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
          locale={{ emptyText: <EmptyText>{t('security.invitations.none')}</EmptyText> }}
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
                row.delivery === 'existing_account' ? (
                  t('invitation_delivery.existing_account')
                ) : (
                  <Flex vertical gap={2}>
                    {dates.format(row.expires_at)}
                    {row.earlier_links_work && waiting(row) && (
                      <Typography.Text type="secondary" data-testid="invitation-earlier-links">
                        {t('security.invitations.earlier_links_work')}
                      </Typography.Text>
                    )}
                  </Flex>
                ),
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
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={invitationField}
        opened={invitationView(tried?.row)}
        latest={invitationView(live)}
        onReload={() => {
          conflict.clear();
          setTried(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (tried !== undefined) {
            run(tried.row, tried.action, conflict.latestVersion ?? live?.version);
          }
          setTried(undefined);
        }}
      />
    </Card>
  );
}
