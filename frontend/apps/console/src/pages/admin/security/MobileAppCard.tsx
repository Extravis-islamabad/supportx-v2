import { Alert, App, Card, Flex, Input, InputNumber, Space, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIdentitySettings,
  useSaveMobilePolicy,
  type IdentitySettings,
  type MobilePolicyInput,
} from '@supportx/api-client';
import {
  ConflictDialog,
  FormProblem,
  lengthLimit,
  markHandled,
  useConflict,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { editable, useSettingName } from './conflict';
import { FieldNote } from './FieldNote';

const LANGUAGES = ['en', 'ar', 'ur'] as const;
type Language = (typeof LANGUAGES)[number];
// 0206's bounds (the server checks the same).
const UNLOCK_MIN = 1;
const UNLOCK_MAX = 60;
const MESSAGE_MAX = 500;
const MIN_IDLE_MINUTES = 5;
const MAX_IDLE_MINUTES = 1440;
const MAX_ABSOLUTE_HOURS = 720;

interface Draft {
  allowed: boolean;
  message: Record<Language, string>;
  mfa: boolean;
  unlock: boolean;
  unlockAfter: number | null;
  ownLimits: boolean;
  idleMinutes: number | null;
  absoluteHours: number | null;
  clear: boolean;
}

function draftFrom(saved: IdentitySettings): Draft {
  const message = saved.mobile_refusal_message ?? {};
  return {
    allowed: saved.mobile_allowed,
    message: { en: message.en ?? '', ar: message.ar ?? '', ur: message.ur ?? '' },
    mfa: saved.mobile_mfa_required,
    unlock: saved.mobile_device_unlock_required,
    unlockAfter: saved.mobile_unlock_after_minutes,
    ownLimits: saved.mobile_idle_seconds != null,
    idleMinutes: saved.mobile_idle_seconds == null ? 60 : saved.mobile_idle_seconds / 60,
    absoluteHours:
      saved.mobile_absolute_seconds == null ? 12 : saved.mobile_absolute_seconds / 3600,
    clear: saved.mobile_clear_on_sign_out,
  };
}

function problems(t: ReturnType<typeof useLabel>, draft: Draft): Record<string, string> {
  const found: Record<string, string> = {};
  const after = draft.unlockAfter;
  if (after === null || !Number.isInteger(after) || after < UNLOCK_MIN || after > UNLOCK_MAX) {
    found.mobile_unlock_after_minutes = t('errors.field.mobile_out_of_range');
  }
  for (const language of LANGUAGES) {
    if (draft.message[language].trim().length > MESSAGE_MAX) {
      found.mobile_refusal_message = t('errors.field.mobile_too_long');
    }
  }
  if (draft.ownLimits) {
    const idle = draft.idleMinutes;
    const absolute = draft.absoluteHours;
    if (
      idle === null ||
      !Number.isInteger(idle) ||
      idle < MIN_IDLE_MINUTES ||
      idle > MAX_IDLE_MINUTES
    ) {
      found.mobile_idle_seconds = t('errors.field.session_idle_out_of_range', {
        min: MIN_IDLE_MINUTES,
        max: MAX_IDLE_MINUTES,
      });
    }
    if (
      absolute === null ||
      absolute <= 0 ||
      absolute > MAX_ABSOLUTE_HOURS ||
      (idle !== null && absolute * 60 < idle)
    ) {
      found.mobile_absolute_seconds = t('errors.field.session_absolute_out_of_range', {
        max: MAX_ABSOLUTE_HOURS,
      });
    }
  }
  return found;
}

function bodyOf(draft: Draft): MobilePolicyInput {
  const written = LANGUAGES.filter((l) => draft.message[l].trim() !== '');
  return {
    allowed: draft.allowed,
    refusal_message:
      written.length === 0
        ? null
        : Object.fromEntries(written.map((l) => [l, draft.message[l].trim()])),
    mfa_required: draft.mfa,
    device_unlock_required: draft.unlock,
    unlock_after_minutes: draft.unlockAfter ?? 5,
    idle_seconds: draft.ownLimits ? Math.round((draft.idleMinutes ?? 0) * 60) : null,
    absolute_seconds: draft.ownLimits ? Math.round((draft.absoluteHours ?? 0) * 3600) : null,
    clear_on_sign_out: draft.clear,
  };
}

/**
 * The mobile app (WP-057 S6b; REQ-SEC-047). Enforced by the server: whether the app may sign in
 * (with the organisation's message), a second factor on mobile, the session's length. Enforced
 * by the app on the device: the unlock after time in the background, clearing data at sign-out.
 * Saves only its own fields; a save another admin made first opens the conflict dialog.
 */
export function MobileAppCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useIdentitySettings();
  const save = useSaveMobilePolicy();
  const [edited, setDraft] = useState<Draft | null>(null);
  const [refused, setRefused] = useState<Record<string, string>>({});
  const problem = useFormProblem();
  const conflict = useConflict();
  const settingName = useSettingName();
  const [base, setBase] = useState<IdentitySettings>();
  if (settings.data === undefined) return <Card loading data-testid="security-mobile" />;
  const saved = settings.data;
  const draft = edited ?? draftFrom(saved);
  const typed = problems(t, draft);
  const shown = { ...refused, ...typed };
  const update = (change: Partial<Draft>, field: string) => {
    if (edited === null) setBase(saved);
    setDraft({ ...draft, ...change });
    setRefused((current) =>
      Object.fromEntries(Object.entries(current).filter(([f]) => f !== field)),
    );
  };
  const submit = (version: number) => {
    problem.clear();
    save.mutate(
      { body: bodyOf(draft), version },
      {
        onSuccess: (next) => {
          setDraft(draftFrom(next));
          setRefused({});
          void message.success(t('security.mobile.saved'));
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
            void settings.refetch();
            return;
          }
          problem.show(error);
        },
      },
    );
  };
  const toggle = (
    id: string,
    checked: boolean,
    onChange: (on: boolean) => void,
    label: string,
    help: string,
  ) => (
    <Flex vertical gap={4}>
      <Space>
        <Switch
          checked={checked}
          onChange={onChange}
          aria-labelledby={`${id}-label`}
          data-testid={id}
        />
        <Typography.Text id={`${id}-label`}>{label}</Typography.Text>
      </Space>
      <Typography.Text type="secondary">{help}</Typography.Text>
    </Flex>
  );
  return (
    <Card title={t('security.mobile.title')} data-testid="security-mobile">
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.mobile.intro')}
        </Typography.Paragraph>
        {toggle(
          'security-mobile-allowed',
          draft.allowed,
          (on) => {
            update({ allowed: on }, 'mobile_allowed');
          },
          t('security.mobile.allowed'),
          t(draft.allowed ? 'security.mobile.allowed_on' : 'security.mobile.allowed_off'),
        )}
        {!draft.allowed && (
          <FieldNote id="security-mobile-message" message={shown.mobile_refusal_message ?? null}>
            <Typography.Text strong>{t('security.mobile.message')}</Typography.Text>
            <Typography.Text type="secondary">{t('security.mobile.message_help')}</Typography.Text>
            {LANGUAGES.map((language) => (
              <Flex key={language} vertical gap={2}>
                <label htmlFor={`security-mobile-message-${language}`}>
                  {t(`locale.${language}`)}
                </label>
                <Input.TextArea
                  id={`security-mobile-message-${language}`}
                  dir={language === 'en' ? 'ltr' : 'rtl'}
                  value={draft.message[language]}
                  count={lengthLimit(MESSAGE_MAX)}
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  onChange={(event) => {
                    update(
                      { message: { ...draft.message, [language]: event.target.value } },
                      'mobile_refusal_message',
                    );
                  }}
                  data-testid={`security-mobile-message-${language}`}
                />
              </Flex>
            ))}
          </FieldNote>
        )}
        {toggle(
          'security-mobile-mfa',
          draft.mfa,
          (on) => {
            update({ mfa: on }, 'mobile_mfa_required');
          },
          t('security.mobile.mfa'),
          t('security.mobile.mfa_help'),
        )}
        {toggle(
          'security-mobile-own-limits',
          draft.ownLimits,
          (on) => {
            update({ ownLimits: on }, 'mobile_idle_seconds');
          },
          t('security.mobile.own_limits'),
          t(draft.ownLimits ? 'security.mobile.own_limits_on' : 'security.mobile.own_limits_off'),
        )}
        {draft.ownLimits && (
          <Space wrap size={24} align="start">
            <FieldNote id="security-mobile-idle" message={shown.mobile_idle_seconds ?? null}>
              <label htmlFor="security-mobile-idle">{t('security.sessions.idle')}</label>
              <InputNumber
                id="security-mobile-idle"
                value={draft.idleMinutes}
                onChange={(value) => {
                  update({ idleMinutes: value }, 'mobile_idle_seconds');
                }}
                suffix={t('security.sessions.minutes')}
                style={{ width: 168 }}
                status={shown.mobile_idle_seconds ? 'error' : undefined}
                data-testid="security-mobile-idle"
              />
            </FieldNote>
            <FieldNote
              id="security-mobile-absolute"
              message={shown.mobile_absolute_seconds ?? null}
            >
              <label htmlFor="security-mobile-absolute">{t('security.sessions.absolute')}</label>
              <InputNumber
                id="security-mobile-absolute"
                value={draft.absoluteHours}
                onChange={(value) => {
                  update({ absoluteHours: value }, 'mobile_absolute_seconds');
                }}
                suffix={t('security.sessions.hours')}
                style={{ width: 168 }}
                status={shown.mobile_absolute_seconds ? 'error' : undefined}
                data-testid="security-mobile-absolute"
              />
            </FieldNote>
          </Space>
        )}
        <Alert
          type="info"
          showIcon
          message={t('security.mobile.on_device')}
          description={t('security.mobile.on_device_help')}
          data-testid="security-mobile-on-device"
        />
        {toggle(
          'security-mobile-unlock',
          draft.unlock,
          (on) => {
            update({ unlock: on }, 'mobile_device_unlock_required');
          },
          t('security.mobile.unlock'),
          t('security.mobile.unlock_help'),
        )}
        {draft.unlock && (
          <FieldNote
            id="security-mobile-unlock-after"
            message={shown.mobile_unlock_after_minutes ?? null}
          >
            <label htmlFor="security-mobile-unlock-after">
              {t('security.mobile.unlock_after')}
            </label>
            <InputNumber
              id="security-mobile-unlock-after"
              value={draft.unlockAfter}
              onChange={(value) => {
                update({ unlockAfter: value }, 'mobile_unlock_after_minutes');
              }}
              suffix={t('security.sessions.minutes')}
              style={{ width: 168 }}
              status={shown.mobile_unlock_after_minutes ? 'error' : undefined}
              data-testid="security-mobile-unlock-after"
            />
          </FieldNote>
        )}
        {toggle(
          'security-mobile-clear',
          draft.clear,
          (on) => {
            update({ clear: on }, 'mobile_clear_on_sign_out');
          },
          t('security.mobile.clear'),
          t('security.mobile.clear_help'),
        )}
        <div>
          <FormProblem problem={problem} />
          <WriteButton
            loading={save.isPending}
            disabled={Object.keys(typed).length > 0 || edited === null}
            onClick={() => {
              submit(saved.version);
            }}
            data-testid="security-mobile-save"
          >
            {t('actions.save')}
          </WriteButton>
        </div>
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
