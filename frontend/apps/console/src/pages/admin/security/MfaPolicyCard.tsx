import { App, Card, Flex, InputNumber, Segmented, Space, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIdentitySettings,
  useMfaPolicy,
  useSaveIdentitySettings,
  useSetMfaMode,
  type MfaMode,
  type MfaRole,
} from '@supportx/api-client';
import { reportError, useLabel, WriteButton } from '@supportx/ui';

import { FieldNote } from './FieldNote';

const MODES: MfaMode[] = ['off', 'optional', 'required'];
const MAX_GRACE_DAYS = 30; // Appendix A: 7 days, at most 30 (REQ-SEC-024)

/** Days to set MFA up once it is required; saved with the sign-in settings. */
function GraceDays() {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useIdentitySettings();
  const save = useSaveIdentitySettings();
  const [edited, setEdited] = useState<number | null | undefined>(undefined);
  if (settings.data === undefined) return null;
  const { version, mfa_grace_days: saved } = settings.data;
  const days = edited === undefined ? saved : edited;
  const bad = days === null || !Number.isInteger(days) || days < 0 || days > MAX_GRACE_DAYS;
  return (
    <Space wrap align="end" size={12}>
      <FieldNote
        id="security-mfa-grace"
        message={
          bad ? t('errors.field.mfa_grace_out_of_range', { min: 0, max: MAX_GRACE_DAYS }) : null
        }
      >
        <label htmlFor="security-mfa-grace">{t('security.mfa.grace')}</label>
        <InputNumber
          id="security-mfa-grace"
          value={days}
          onChange={(value) => {
            setEdited(value);
          }}
          suffix={t('security.password.days')}
          style={{ width: 168 }}
          status={bad ? 'error' : undefined}
          aria-describedby="security-mfa-grace-problem"
          data-testid="security-mfa-grace"
        />
      </FieldNote>
      <WriteButton
        loading={save.isPending}
        disabled={bad || edited === undefined || days === saved}
        onClick={() => {
          save.mutate(
            { body: { mfa_grace_days: days ?? 0 }, version },
            {
              onSuccess: () => {
                setEdited(undefined);
                void message.success(t('security.invitations.saved'));
              },
              onError: (error) => {
                if (error instanceof ApiError && error.isConflict) {
                  void settings.refetch();
                  void message.warning(t('security.changed_elsewhere'));
                  return;
                }
                reportError(error);
              },
            },
          );
        }}
        data-testid="security-mfa-grace-save"
      >
        {t('actions.save')}
      </WriteButton>
    </Space>
  );
}

/**
 * Two-step sign-in (WP-039 session 3; REQ-SEC-022, 024): off, optional or required per role,
 * with how many holders have set it up (AC3). Required MFA gives the grace period below; after
 * it, people without an authenticator app can only set one up.
 */
export function MfaPolicyCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const policy = useMfaPolicy();
  const setMode = useSetMfaMode();
  const roleName = (role: MfaRole) => (role.key === null ? role.name : t(`role.${role.key}`));
  return (
    <Card title={t('security.mfa.title')} data-testid="security-mfa">
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.mfa.intro')}
        </Typography.Paragraph>
        <GraceDays />
        <Table<MfaRole>
          rowKey="role_id"
          size="small"
          pagination={false}
          scroll={{ x: true }}
          loading={policy.isLoading}
          dataSource={policy.data?.roles ?? []}
          data-testid="security-mfa-roles"
          columns={[
            { key: 'role', title: t('security.mfa.role'), render: (_, role) => roleName(role) },
            {
              key: 'mode',
              title: t('security.mfa.mode'),
              render: (_, role) => (
                <Segmented<MfaMode>
                  size="small"
                  value={role.mode}
                  disabled={setMode.isPending}
                  aria-label={t('security.mfa.mode_for', { role: roleName(role) })}
                  data-testid={`security-mfa-mode-${role.key ?? role.role_id}`}
                  options={MODES.map((value) => ({ value, label: t(`mfa_mode.${value}`) }))}
                  onChange={(mode) => {
                    setMode.mutate(
                      { roleId: role.role_id, mode, version: role.version },
                      {
                        onSuccess: () => {
                          void message.success(t('security.mfa.saved', { role: roleName(role) }));
                        },
                        onError: (error) => {
                          if (error instanceof ApiError && error.isConflict) {
                            void policy.refetch();
                            void message.warning(t('security.changed_elsewhere'));
                            return;
                          }
                          reportError(error);
                        },
                      },
                    );
                  }}
                />
              ),
            },
            {
              key: 'enrolled',
              title: t('security.mfa.enrolled'),
              render: (_, role) => (
                <span data-testid={`security-mfa-count-${role.key ?? role.role_id}`}>
                  {t('security.mfa.count', { enrolled: role.enrolled, holders: role.holders })}
                </span>
              ),
            },
          ]}
        />
      </Flex>
    </Card>
  );
}
