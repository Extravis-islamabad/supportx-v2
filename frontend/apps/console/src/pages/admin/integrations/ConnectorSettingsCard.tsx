import { App, Card, Flex, InputNumber, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  ApiError,
  queryKeys,
  useConnectorSettings,
  useSaveConnectorSettings,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import { FormProblem, markHandled, useFormProblem, useLabel, WriteButton } from '@supportx/ui';

// WP-040 (D-041): the tenant's connector defaults, editable by integrations.manage. Another
// admin's save arrives live (integrations.connector_settings_changed).

type Field = 'failing_after_runs' | 'error_retention_days' | 'sync_minutes';
const FIELDS: { name: Field; min: number; max: number }[] = [
  { name: 'failing_after_runs', min: 1, max: 20 },
  { name: 'error_retention_days', min: 7, max: 365 },
  { name: 'sync_minutes', min: 15, max: 1440 },
];

export function ConnectorSettingsCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const settings = useConnectorSettings();
  const save = useSaveConnectorSettings();
  const problem = useFormProblem();
  // Only what this admin changed; the rest follows the server, live.
  const [draft, setDraft] = useState<Partial<Record<Field, number>>>({});
  const [refused, setRefused] = useState<Record<string, string>>({});
  useTenantChannel((event) => {
    if (event.type === 'integrations.connector_settings_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.connectors.settings });
    }
  });
  const saved = settings.data;
  if (saved === undefined) return null;
  const value = (name: Field) => draft[name] ?? saved[name];
  const changed = FIELDS.some(({ name }) => value(name) !== saved[name]);
  const submit = () => {
    problem.clear();
    save.mutate(
      {
        body: Object.fromEntries(FIELDS.map(({ name }) => [name, value(name)])),
        version: saved.version,
      },
      {
        onSuccess: () => {
          setDraft({});
          void message.success(t('connector_settings.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
            markHandled(error);
            setRefused(
              Object.fromEntries(
                error.fieldErrors.map((f) => [f.field.replace(/^body\./, ''), f.message_key]),
              ),
            );
            return;
          }
          problem.show(error);
        },
      },
    );
  };
  return (
    <Card title={t('connector_settings.title')} data-testid="connector-settings">
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('connector_settings.intro')}
        </Typography.Paragraph>
        <FormProblem problem={problem} />
        <Flex gap={24} wrap>
          {FIELDS.map(({ name, min, max }) => (
            <Flex key={name} vertical gap={4} style={{ minWidth: 220 }}>
              <label htmlFor={`connector-settings-${name}`}>
                {t(`connector_settings.${name}`)}
              </label>
              <InputNumber
                id={`connector-settings-${name}`}
                min={min}
                max={max}
                value={value(name)}
                status={refused[name] === undefined ? undefined : 'error'}
                aria-describedby={`connector-settings-${name}-help`}
                onChange={(next) => {
                  setDraft({ ...draft, [name]: next ?? saved[name] });
                  setRefused({});
                }}
                data-testid={`connector-settings-${name}`}
              />
              <Typography.Text type="secondary" id={`connector-settings-${name}-help`}>
                {refused[name] === undefined
                  ? t(`connector_settings.${name}_help`, { min, max })
                  : t(refused[name], { min, max })}
              </Typography.Text>
            </Flex>
          ))}
        </Flex>
        <Flex>
          <WriteButton
            type="primary"
            disabled={!changed}
            loading={save.isPending}
            onClick={submit}
            data-testid="connector-settings-save"
          >
            {t('actions.save')}
          </WriteButton>
        </Flex>
      </Flex>
    </Card>
  );
}
