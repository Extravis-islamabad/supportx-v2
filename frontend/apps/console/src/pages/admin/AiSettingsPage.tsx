import { Alert, App, Card, Checkbox, Flex, InputNumber, Space, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  type AiSettings,
  type AiSettingsInput,
  useAiSettings,
  useSaveAiSettings,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import { NoAccess, reportError, useAccess, useLabel, useLicence, WriteButton } from '@supportx/ui';

// WP-037 (REQ-AI-027, 018, 031): Admin › AI. The master switch, a switch per feature grouped by
// area (switching off says what happens, and takes effect for everyone at once), masking for the
// local model, and how long AI call text is kept. Live: another admin's change shows at once.

const AREAS = ['writing', 'summaries', 'predictions', 'knowledge'] as const;

function Row({
  id,
  label,
  help,
  control,
}: {
  id: string;
  label: string;
  help?: string;
  control: React.ReactNode;
}) {
  return (
    <Flex justify="space-between" align="start" gap={16}>
      <Space direction="vertical" size={0}>
        <Typography.Text id={id}>{label}</Typography.Text>
        {help !== undefined && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {help}
          </Typography.Text>
        )}
      </Space>
      {control}
    </Flex>
  );
}

const SUMMARY_SOURCES = ['description', 'replies', 'public_notes', 'private_notes'] as const;

export function AiSettingsPage() {
  const t = useLabel();
  // A read-only licence: the switches show the state but change nothing (coverage §17 item 3).
  const { writable } = useLicence();
  const { can } = useAccess();
  const { modal, message } = App.useApp();
  const settings = useAiSettings(can('ai.manage'));
  const save = useSaveAiSettings();
  const [days, setDays] = useState<number | null>(null);
  useTenantChannel((m) => {
    if (m.type === 'ai.settings_changed') void settings.refetch();
  });

  if (!can('ai.manage')) return <NoAccess titleKey="nav.admin_ai" />;
  if (settings.data === undefined) return null;
  const saved: AiSettings = settings.data;

  const change = (body: AiSettingsInput) => {
    save.mutate(
      { body, version: saved.version },
      {
        onSuccess: () => void message.success(t('ai_settings.saved')),
        onError: reportError,
      },
    );
  };
  // Switching off asks first and says what happens to results already made (REQ-AI-027).
  const confirmOff = (title: string, apply: () => void) => {
    modal.confirm({
      title,
      content: t('ai_settings.off_effect'),
      okText: t('ai_settings.switch_off'),
      okButtonProps: { danger: true },
      cancelText: t('actions.cancel'),
      onOk: apply,
    });
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }} data-testid="ai-settings">
      <Card title={t('ai_settings.title')}>
        <Row
          id="ai-master"
          label={t('ai_settings.master')}
          help={t('ai_settings.master_help')}
          control={
            <Switch
              checked={saved.enabled}
              disabled={!writable}
              loading={save.isPending}
              aria-labelledby="ai-master"
              data-testid="ai-master"
              onChange={(on) => {
                if (on) change({ enabled: true });
                else
                  confirmOff(t('ai_settings.confirm_master_off'), () => {
                    change({ enabled: false });
                  });
              }}
            />
          }
        />
      </Card>
      <Card title={t('ai_settings.features')}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          {AREAS.map((area) => {
            const features = saved.features.filter((f) => f.area === area);
            if (features.length === 0) return null;
            return (
              <section key={area} aria-labelledby={`ai-area-${area}`}>
                <Typography.Title level={3} id={`ai-area-${area}`} style={{ fontSize: 14 }}>
                  {t(`ai_area.${area}`)}
                </Typography.Title>
                <Space direction="vertical" style={{ width: '100%' }}>
                  {features.map((feature) => {
                    const off = saved.disabled_features.includes(feature.code);
                    const name = t(`ai_feature.${feature.code}`);
                    return (
                      <Row
                        key={feature.code}
                        id={`ai-feature-${feature.code}`}
                        label={name}
                        control={
                          <Switch
                            checked={!off}
                            disabled={!saved.enabled || !writable}
                            loading={save.isPending}
                            aria-labelledby={`ai-feature-${feature.code}`}
                            data-testid={`ai-feature-${feature.code}`}
                            onChange={(on) => {
                              const next = on
                                ? saved.disabled_features.filter((c) => c !== feature.code)
                                : [...saved.disabled_features, feature.code];
                              if (on) change({ disabled_features: next });
                              else
                                confirmOff(t('ai_settings.confirm_off', { feature: name }), () => {
                                  change({ disabled_features: next });
                                });
                            }}
                          />
                        }
                      />
                    );
                  })}
                </Space>
              </section>
            );
          })}
        </Space>
      </Card>
      <Card title={t('ai_settings.privacy')}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Typography.Text type="secondary" data-testid="ai-model">
            {t('ai_settings.model')}:{' '}
            {saved.provider.name === 'fake'
              ? // The built-in stand-in is never named: no model is connected (QA6S-AI-01).
                t('ai_settings.model_none')
              : t('ai_settings.model_value', {
                  model: saved.provider.model,
                  where: t(saved.provider.external ? 'ai_settings.external' : 'ai_settings.local'),
                })}
          </Typography.Text>
          {saved.provider.external ? (
            <Typography.Text>{t('ai_settings.always_masked')}</Typography.Text>
          ) : (
            <Row
              id="ai-mask-local"
              label={t('ai_settings.mask_local')}
              help={t('ai_settings.mask_local_help')}
              control={
                <Switch
                  checked={saved.mask_local}
                  disabled={!writable}
                  loading={save.isPending}
                  aria-labelledby="ai-mask-local"
                  data-testid="ai-mask-local"
                  onChange={(on) => {
                    change({ mask_local: on });
                  }}
                />
              }
            />
          )}
          {/* WP-038: what conversation summaries may read; at least one part. */}
          <Row
            id="ai-summary-sources"
            label={t('ai_settings.summary_sources')}
            help={t('ai_settings.summary_sources_help')}
            control={
              <Checkbox.Group
                value={saved.summary_sources}
                disabled={save.isPending || !writable}
                aria-labelledby="ai-summary-sources"
                data-testid="ai-summary-sources"
                options={SUMMARY_SOURCES.map((code) => ({
                  value: code,
                  label: t(`ai_summary_source.${code}`),
                  disabled: saved.summary_sources.length === 1 && saved.summary_sources[0] === code,
                }))}
                onChange={(values) => {
                  if (values.length > 0) change({ summary_sources: values });
                }}
              />
            }
          />
          {/* D-131: said where the setting is, not only in the docs. */}
          <Alert
            type="info"
            showIcon
            role="note"
            message={t('ai_settings.no_training')}
            data-testid="ai-no-training"
          />
          <Row
            id="ai-retention"
            label={t('ai_settings.retention')}
            help={t('ai_settings.retention_help')}
            control={
              // Wraps as a whole: at 390 px the unit never breaks one letter a line between the
              // number and Save (QA9-V-11).
              <Space wrap>
                <InputNumber
                  min={1}
                  max={365}
                  value={days ?? saved.log_retention_days}
                  onChange={(value) => {
                    setDays(value);
                  }}
                  aria-labelledby="ai-retention"
                  data-testid="ai-retention"
                />
                <Typography.Text style={{ whiteSpace: 'nowrap' }}>
                  {t('ai_settings.days')}
                </Typography.Text>
                <WriteButton
                  disabled={days === null || days === saved.log_retention_days}
                  loading={save.isPending}
                  data-testid="ai-retention-save"
                  onClick={() => {
                    if (days !== null) change({ log_retention_days: days });
                    setDays(null);
                  }}
                >
                  {t('actions.save')}
                </WriteButton>
              </Space>
            }
          />
        </Space>
      </Card>
    </Space>
  );
}
