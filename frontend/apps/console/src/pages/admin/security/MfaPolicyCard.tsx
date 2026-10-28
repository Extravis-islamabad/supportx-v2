import { App, Card, Flex, InputNumber, Segmented, Space, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  type IdentitySettings,
  useIdentitySettings,
  useMfaPolicy,
  useSaveIdentitySettings,
  useSetMfaMode,
  type MfaMode,
  type MfaRole,
} from '@supportx/api-client';
import {
  ConflictDialog,
  FormProblem,
  reportError,
  useConflict,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { editable, useSettingName } from './conflict';
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
  // A refused save is shown here, not as a toast (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // A save another admin made first (409): who, when and what, in the shared dialog (BUG-05).
  const conflict = useConflict();
  const settingName = useSettingName();
  // The settings when the edit began: the dialog compares them with the live ones.
  const [base, setBase] = useState<IdentitySettings>();
  if (settings.data === undefined) return null;
  const current = settings.data;
  const { version, mfa_grace_days: saved } = settings.data;
  const days = edited === undefined ? saved : edited;
  const bad = days === null || !Number.isInteger(days) || days < 0 || days > MAX_GRACE_DAYS;
  const submit = (at: number) => {
    problem.clear();
    save.mutate(
      { body: { mfa_grace_days: days ?? 0 }, version: at },
      {
        onSuccess: () => {
          setEdited(undefined);
          void message.success(t('security.invitations.saved'));
        },
        onError: (error) => {
          if (conflict.take(error)) {
            // Another admin saved first: fetch their version; the dialog asks (D-103 (4)).
            void settings.refetch();
            return;
          }
          problem.show(error);
        },
      },
    );
  };
  return (
    <div>
      <FormProblem problem={problem} />
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
              if (edited === undefined) setBase(current);
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
            submit(version);
          }}
          data-testid="security-mfa-grace-save"
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
  // A role's mode another admin changed first (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflict();
  const [tried, setTried] = useState<{ role: MfaRole; mode: MfaMode }>();
  const live = policy.data?.roles.find((r) => r.role_id === tried?.role.role_id);
  const change = (role: MfaRole, mode: MfaMode, version = role.version) => {
    setMode.mutate(
      { roleId: role.role_id, mode, version },
      {
        onSuccess: () => {
          void message.success(t('security.mfa.saved', { role: roleName(role) }));
        },
        onError: (error) => {
          if (conflict.take(error)) {
            setTried({ role, mode });
            void policy.refetch();
            return;
          }
          reportError(error);
        },
      },
    );
  };
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
                    change(role, mode);
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
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={() => t('security.mfa.mode_for', { role: tried ? roleName(tried.role) : '' })}
        // Only the mode is changed here (not the enrolment counts).
        opened={tried && { mode: tried.role.mode }}
        latest={live && { mode: live.mode }}
        onReload={() => {
          conflict.clear();
          setTried(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (tried !== undefined) {
            change(tried.role, tried.mode, conflict.latestVersion ?? live?.version);
          }
          setTried(undefined);
        }}
      />
    </Card>
  );
}
