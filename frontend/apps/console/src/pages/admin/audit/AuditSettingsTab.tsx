import { Alert, Button, Card, Checkbox, Form, InputNumber, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  useAuditSettings,
  useUpdateAuditSettings,
  type AuditReadCategory,
  type AuditSettings,
} from '@supportx/api-client';
import { useAccess, useLabel } from '@supportx/ui';

import { numberProblem } from '../../../numbers';

import { ProblemAlert } from './ProblemAlert';

const NUMBERS = [
  'retention_days',
  'read_window_minutes',
  'refusal_threshold',
  'refusal_window_minutes',
] as const;
type NumberSetting = (typeof NUMBERS)[number];
const READS: AuditReadCategory[] = [
  'audit_log',
  'access_information',
  'security_settings',
  'secrets',
  'exports',
];

/**
 * Audit settings (D-076 item 5): retention (1 to 10 years), the read window, the probing alert and
 * which sensitive reads are logged. Editable only with `audit.manage`; read-only for auditors.
 * Every change is itself an audit entry; the audit log itself is always logged when read.
 */
export function AuditSettingsTab() {
  const settings = useAuditSettings();
  if (settings.data === undefined) return <Card loading />;
  // A new version (saved here or by someone else) starts a fresh form.
  return <SettingsForm key={settings.data.version} saved={settings.data} />;
}

function SettingsForm({ saved }: { saved: AuditSettings }) {
  const t = useLabel();
  const { can } = useAccess();
  const editable = can('audit.manage');
  const update = useUpdateAuditSettings();
  const [draft, setDraft] = useState<AuditSettings>(saved);

  const setNumber = (key: NumberSetting, value: number | null) => {
    if (value !== null) setDraft({ ...draft, [key]: value });
  };
  const changed = JSON.stringify(draft) !== JSON.stringify(saved);
  // Out-of-range numbers are refused at the field, never clamped (QA WP-026 BUG-03).
  const problemOf = (key: NumberSetting) => {
    const [min = 1, max = 3650] = draft.limits[key] ?? [];
    return numberProblem(t, draft[key], { min, max, whole: true });
  };
  const invalid = NUMBERS.some((key) => problemOf(key) !== null);

  return (
    <Card title={t('audit.ui.tab.settings')}>
      {!editable && (
        <Alert
          type="info"
          showIcon
          message={t('audit.ui.settings.read_only')}
          style={{ marginBottom: 16 }}
        />
      )}
      <Form layout="vertical" disabled={!editable} style={{ maxWidth: 560 }}>
        {NUMBERS.map((key) => {
          const [min = 1, max = 3650] = draft.limits[key] ?? [];
          return (
            <Form.Item
              key={key}
              label={t(`audit.setting.${key}`)}
              validateStatus={problemOf(key) === null ? undefined : 'error'}
              help={
                problemOf(key) === null ? (
                  t(`audit.setting.${key}.help`, { min, max })
                ) : (
                  <span role="alert" data-testid={`audit-setting-${key}-error`}>
                    {problemOf(key)}
                  </span>
                )
              }
            >
              <InputNumber
                value={draft[key]}
                onChange={(value) => {
                  setNumber(key, value);
                }}
                data-testid={`audit-setting-${key}`}
              />
            </Form.Item>
          );
        })}
        <Form.Item label={t('audit.setting.read_categories')}>
          <Space direction="vertical">
            {READS.map((category) => (
              <Checkbox
                key={category}
                checked={draft.read_categories.includes(category)}
                disabled={category === 'audit_log'}
                onChange={(event) => {
                  const others = draft.read_categories.filter((c) => c !== category);
                  setDraft({
                    ...draft,
                    read_categories: event.target.checked ? [...others, category] : others,
                  });
                }}
                data-testid={`audit-read-${category}`}
              >
                {t(`audit_read_category.${category}`)}
              </Checkbox>
            ))}
            <Typography.Text type="secondary">
              {t('audit.setting.read_categories.help')}
            </Typography.Text>
          </Space>
        </Form.Item>
        {editable && (
          <Button
            type="primary"
            disabled={!changed || invalid}
            loading={update.isPending}
            data-testid="audit-settings-save"
            onClick={() => {
              update.mutate({
                version: saved.version,
                body: {
                  retention_days: draft.retention_days,
                  read_window_minutes: draft.read_window_minutes,
                  refusal_threshold: draft.refusal_threshold,
                  refusal_window_minutes: draft.refusal_window_minutes,
                  read_categories: draft.read_categories,
                },
              });
            }}
          >
            {t('audit.ui.settings.save')}
          </Button>
        )}
      </Form>
      {update.error !== null && <ProblemAlert error={update.error} />}
    </Card>
  );
}
