import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Flex,
  InputNumber,
  Space,
  Switch,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useApplyPasswordPolicy,
  useIdentitySettings,
  useSaveIdentitySettings,
  type IdentitySettings,
  type IdentitySettingsInput,
} from '@supportx/api-client';
import {
  ConflictDialog,
  FormProblem,
  markHandled,
  reportError,
  ToneTag,
  useConflict,
  useFormProblem,
  useLabel,
  WriteButton,
  type Tone,
} from '@supportx/ui';

import { editable, useSettingName } from './conflict';
import { FieldNote } from './FieldNote';

// Appendix A and domain/password_policy.py (the server checks the same; REQ-SEC-005).
const LIMITS = {
  password_min_length: { min: 8, max: 64 },
  password_history: { min: 0, max: 24 },
  password_expiry_days: { min: 0, max: 365 },
} as const;
type NumberField = keyof typeof LIMITS;
const NEEDS = ['password_upper', 'password_lower', 'password_digits', 'password_special'] as const;
type Draft = Pick<IdentitySettings, (typeof NEEDS)[number] | 'password_breached_check'> &
  Record<NumberField, number | null>;

const STATE_TONE: Record<IdentitySettings['password_policy_state'], Tone> = {
  default: 'default',
  applying: 'info',
  applied: 'success',
  failed: 'error',
};

function draftFrom(saved: IdentitySettings): Draft {
  return {
    password_min_length: saved.password_min_length,
    password_upper: saved.password_upper,
    password_lower: saved.password_lower,
    password_digits: saved.password_digits,
    password_special: saved.password_special,
    password_history: saved.password_history,
    password_expiry_days: saved.password_expiry_days,
    password_breached_check: saved.password_breached_check,
  };
}

function problems(t: ReturnType<typeof useLabel>, draft: Draft): Record<string, string> {
  const found: Record<string, string> = {};
  for (const field of Object.keys(LIMITS) as NumberField[]) {
    const value = draft[field];
    const { min, max } = LIMITS[field];
    if (value === null || !Number.isInteger(value) || value < min || value > max) {
      found[field] = t('errors.field.password_policy_out_of_range', { min, max });
    }
  }
  return found;
}

/**
 * The installation's password policy (WP-039 session 2; REQ-SEC-005; D-089 D1 c, D2): saved
 * here, written into the sign-in service by a worker. The state says whether that happened; a
 * failure says why and can be applied again. On a multi-tenant installation it is read-only.
 */
export function PasswordPolicyCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useIdentitySettings();
  const save = useSaveIdentitySettings();
  const apply = useApplyPasswordPolicy();
  const [edited, setDraft] = useState<Draft | null>(null);
  const [refused, setRefused] = useState<Record<string, string>>({});
  // A refusal with no field to point at is shown above Save (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // A save another admin made first (409): who, when and what, in the shared dialog (BUG-05).
  const conflict = useConflict();
  const settingName = useSettingName();
  // The settings when the edit began: the dialog compares them with the live ones.
  const [base, setBase] = useState<IdentitySettings>();
  if (settings.data === undefined) return <Card loading data-testid="security-password" />;
  const saved = settings.data;
  const readOnly = !saved.password_policy_editable;
  const draft = edited ?? draftFrom(saved);
  const typed = problems(t, draft);
  const shown = { ...refused, ...typed };
  const update = (change: Partial<Draft>) => {
    if (edited === null) setBase(saved);
    setDraft({ ...draft, ...change });
    setRefused((current) =>
      Object.fromEntries(Object.entries(current).filter(([f]) => !(f in change))),
    );
  };
  const body = (): IdentitySettingsInput => ({
    ...draft,
    password_min_length: draft.password_min_length ?? 0,
    password_history: draft.password_history ?? 0,
    password_expiry_days: draft.password_expiry_days ?? 0,
  });
  const number = (field: NumberField, label: string, suffix: string, hint?: string) => (
    <FieldNote id={`security-${field}`} message={shown[field] ?? null}>
      <label htmlFor={`security-${field}`}>{label}</label>
      <InputNumber
        id={`security-${field}`}
        value={draft[field]}
        disabled={readOnly}
        onChange={(value) => {
          update({ [field]: value });
        }}
        suffix={suffix}
        style={{ width: 168 }}
        status={shown[field] ? 'error' : undefined}
        aria-describedby={`security-${field}-problem`}
        data-testid={`security-${field}`}
      />
      {hint !== undefined && <Typography.Text type="secondary">{hint}</Typography.Text>}
    </FieldNote>
  );

  const submit = (version: number) => {
    problem.clear();
    save.mutate(
      { body: body(), version },
      {
        onSuccess: () => {
          setDraft(null);
          setRefused({});
          void message.success(t('security.password.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
            markHandled(error);
            setRefused(
              Object.fromEntries(
                error.fieldErrors.map((f) => [f.field, t(f.message_key, f.params ?? {})]),
              ),
            );
            return;
          }
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
    <Card
      title={t('security.password.title')}
      extra={
        <ToneTag tone={STATE_TONE[saved.password_policy_state]} testId="security-password-state">
          {t(`password_policy_state.${saved.password_policy_state}`)}
        </ToneTag>
      }
      data-testid="security-password"
    >
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.password.intro')}{' '}
          {t(readOnly ? 'security.password.platform' : 'security.password.installation')}
        </Typography.Paragraph>
        {saved.password_policy_state === 'failed' && (
          <Alert
            type="error"
            showIcon
            data-testid="security-password-failed"
            message={t(
              `password_policy_error.${saved.password_policy_error ?? 'password_policy_refused'}`,
            )}
            action={
              <Button
                size="small"
                loading={apply.isPending}
                onClick={() => {
                  apply.mutate(undefined, { onError: reportError });
                }}
                data-testid="security-password-apply"
              >
                {t('security.password.apply_again')}
              </Button>
            }
          />
        )}
        <Space wrap size={24} align="start">
          {number(
            'password_min_length',
            t('security.password.min_length'),
            t('security.password.characters'),
          )}
          {number(
            'password_history',
            t('security.password.history'),
            t('security.password.passwords'),
            t('security.password.history_hint'),
          )}
          {number(
            'password_expiry_days',
            t('security.password.expiry'),
            t('security.password.days'),
            t('security.password.expiry_hint'),
          )}
        </Space>
        <Flex vertical gap={8} role="group" aria-labelledby="security-password-needs">
          <Typography.Text id="security-password-needs">
            {t('security.password.needs')}
          </Typography.Text>
          <Space wrap size={16}>
            {NEEDS.map((field) => (
              <Checkbox
                key={field}
                checked={draft[field]}
                disabled={readOnly}
                onChange={(event) => {
                  update({ [field]: event.target.checked });
                }}
                data-testid={`security-${field}`}
              >
                {t(`security.password.${field.replace('password_', '')}`)}
              </Checkbox>
            ))}
          </Space>
        </Flex>
        <Flex vertical gap={4}>
          <Space>
            <Switch
              checked={draft.password_breached_check}
              disabled={readOnly}
              onChange={(on) => {
                update({ password_breached_check: on });
              }}
              aria-labelledby="security-password-breached-label"
              data-testid="security-password_breached_check"
            />
            <Typography.Text id="security-password-breached-label">
              {t('security.password.breached')}
            </Typography.Text>
          </Space>
          <Typography.Text type="secondary">{t('security.password.breached_hint')}</Typography.Text>
        </Flex>
        {!readOnly && (
          <div>
            <FormProblem problem={problem} />
            <WriteButton
              type="primary"
              loading={save.isPending}
              disabled={Object.keys(typed).length > 0 || edited === null}
              onClick={() => {
                submit(saved.version);
              }}
              data-testid="security-password-save"
            >
              {t('actions.save')}
            </WriteButton>
          </div>
        )}
      </Flex>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={settingName}
        opened={editable(base)}
        latest={editable(saved)}
        onReload={() => {
          conflict.clear();
          setDraft(null);
          setRefused({});
        }}
        onKeepMine={() => {
          conflict.clear();
          setBase(saved);
          submit(conflict.latestVersion ?? saved.version);
        }}
      />
    </Card>
  );
}
