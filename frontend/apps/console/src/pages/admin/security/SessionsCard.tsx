import { App, Card, Flex, InputNumber, Space, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIdentitySettings,
  useSaveIdentitySettings,
  type IdentitySettings,
  type IdentitySettingsInput,
} from '@supportx/api-client';
import { reportError, useLabel, WriteButton } from '@supportx/ui';

import { FieldNote } from './FieldNote';

type AppName = 'console' | 'portal';
const APPS: AppName[] = ['console', 'portal'];
// Appendix A caps (the server checks the same; REQ-SEC-029).
const MIN_IDLE_MINUTES = 5;
const MAX_IDLE_MINUTES = 1440;
const MAX_ABSOLUTE_HOURS: Record<AppName, number> = { console: 168, portal: 720 };

interface Draft {
  idle: Record<AppName, number | null>;
  absolute: Record<AppName, number | null>;
  createPeople: boolean;
}

function draftFrom(saved: IdentitySettings): Draft {
  return {
    idle: {
      console: saved.console_idle_seconds / 60,
      portal: saved.portal_idle_seconds / 60,
    },
    absolute: {
      console: saved.console_absolute_seconds / 3600,
      portal: saved.portal_absolute_seconds / 3600,
    },
    createPeople: saved.create_people_on_sign_in,
  };
}

/** What is wrong with a typed value, at once (D-091: never changed silently, refused at the field). */
function problems(t: ReturnType<typeof useLabel>, draft: Draft): Record<string, string> {
  const found: Record<string, string> = {};
  for (const app of APPS) {
    const idle = draft.idle[app];
    const absolute = draft.absolute[app];
    if (
      idle === null ||
      !Number.isInteger(idle) ||
      idle < MIN_IDLE_MINUTES ||
      idle > MAX_IDLE_MINUTES
    ) {
      found[`${app}_idle_seconds`] = t('errors.field.session_idle_out_of_range', {
        min: MIN_IDLE_MINUTES,
        max: MAX_IDLE_MINUTES,
      });
    }
    if (
      absolute === null ||
      absolute <= 0 ||
      absolute > MAX_ABSOLUTE_HOURS[app] ||
      (idle !== null && absolute * 60 < idle)
    ) {
      found[`${app}_absolute_seconds`] = t('errors.field.session_absolute_out_of_range', {
        max: MAX_ABSOLUTE_HOURS[app],
      });
    }
  }
  return found;
}

/**
 * Sessions and people creation (WP-039; REQ-SEC-013, REQ-SEC-029): idle and absolute limits for
 * the console and the portal, applying to sessions begun after saving, and whether a first
 * sign-in creates the person.
 */
export function SessionsCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useIdentitySettings();
  const save = useSaveIdentitySettings();
  const [edited, setDraft] = useState<Draft | null>(null);
  const [refused, setRefused] = useState<Record<string, string>>({});
  if (settings.data === undefined) return <Card loading data-testid="security-sessions" />;
  const draft = edited ?? draftFrom(settings.data);
  const typed = problems(t, draft);
  const shown = { ...refused, ...typed };
  const update = (change: Partial<Draft>, field: string) => {
    setDraft({ ...draft, ...change });
    setRefused((current) =>
      Object.fromEntries(Object.entries(current).filter(([f]) => f !== field)),
    );
  };
  const body = (): IdentitySettingsInput => ({
    console_idle_seconds: Math.round((draft.idle.console ?? 0) * 60),
    console_absolute_seconds: Math.round((draft.absolute.console ?? 0) * 3600),
    portal_idle_seconds: Math.round((draft.idle.portal ?? 0) * 60),
    portal_absolute_seconds: Math.round((draft.absolute.portal ?? 0) * 3600),
    create_people_on_sign_in: draft.createPeople,
  });

  return (
    <Card title={t('security.sessions.title')} data-testid="security-sessions">
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.sessions.intro')}
        </Typography.Paragraph>
        {APPS.map((app) => (
          <Flex key={app} vertical gap={8}>
            <Typography.Text strong>{t(`security.sessions.${app}`)}</Typography.Text>
            <Space wrap size={24} align="start">
              <FieldNote id={`security-${app}-idle`} message={shown[`${app}_idle_seconds`] ?? null}>
                <label htmlFor={`security-${app}-idle`}>{t('security.sessions.idle')}</label>
                <InputNumber
                  id={`security-${app}-idle`}
                  value={draft.idle[app]}
                  onChange={(value) => {
                    update({ idle: { ...draft.idle, [app]: value } }, `${app}_idle_seconds`);
                  }}
                  suffix={t('security.sessions.minutes')}
                  style={{ width: 168 }}
                  status={shown[`${app}_idle_seconds`] ? 'error' : undefined}
                  aria-describedby={`security-${app}-idle-problem`}
                  data-testid={`security-${app}-idle`}
                />
              </FieldNote>
              <FieldNote
                id={`security-${app}-absolute`}
                message={shown[`${app}_absolute_seconds`] ?? null}
              >
                <label htmlFor={`security-${app}-absolute`}>
                  {t('security.sessions.absolute')}
                </label>
                <InputNumber
                  id={`security-${app}-absolute`}
                  value={draft.absolute[app]}
                  onChange={(value) => {
                    update(
                      { absolute: { ...draft.absolute, [app]: value } },
                      `${app}_absolute_seconds`,
                    );
                  }}
                  suffix={t('security.sessions.hours')}
                  style={{ width: 168 }}
                  status={shown[`${app}_absolute_seconds`] ? 'error' : undefined}
                  aria-describedby={`security-${app}-absolute-problem`}
                  data-testid={`security-${app}-absolute`}
                />
              </FieldNote>
            </Space>
          </Flex>
        ))}
        <Flex vertical gap={4}>
          <Space>
            <Switch
              checked={draft.createPeople}
              onChange={(on) => {
                update({ createPeople: on }, 'create_people_on_sign_in');
              }}
              aria-labelledby="security-create-people-label"
              data-testid="security-create-people"
            />
            <Typography.Text id="security-create-people-label">
              {t('security.people.create')}
            </Typography.Text>
          </Space>
          <Typography.Text type="secondary">
            {t(draft.createPeople ? 'security.people.create_on' : 'security.people.create_off')}
          </Typography.Text>
        </Flex>
        <div>
          <WriteButton
            type="primary"
            loading={save.isPending}
            disabled={Object.keys(typed).length > 0 || edited === null}
            onClick={() => {
              save.mutate(
                { body: body(), version: settings.data.version },
                {
                  onSuccess: (saved) => {
                    setDraft(draftFrom(saved));
                    setRefused({});
                    void message.success(t('security.sessions.saved'));
                  },
                  onError: (error) => {
                    if (error instanceof ApiError && error.status === 422) {
                      setRefused(
                        Object.fromEntries(
                          error.fieldErrors.map((f) => [f.field, t(f.message_key, f.params ?? {})]),
                        ),
                      );
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
            data-testid="security-sessions-save"
          >
            {t('actions.save')}
          </WriteButton>
        </div>
      </Flex>
    </Card>
  );
}
