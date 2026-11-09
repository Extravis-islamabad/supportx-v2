import { Alert, App, Checkbox, Flex, InputNumber, Space, Switch, Typography } from 'antd';
import { useMemo } from 'react';

import { type AiSettings, useAiSettings, useSaveAiSettings } from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  NoAccess,
  reportError,
  SettingsCard,
  StickySaveBar,
  useAccess,
  useLabel,
  useLicence,
  useSettingsDraft,
} from '@supportx/ui';

// WP-037 (REQ-AI-027, 018, 031): Admin › AI. The master switch, a switch per feature grouped by
// area (switching off says what happens, and takes effect for everyone at once), masking for the
// local model, and how long AI call text is kept. Live: another admin's change shows at once.
// Template E (D-147): cards and one save bar for everything on the page.

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

type Draft = Pick<
  AiSettings,
  'enabled' | 'disabled_features' | 'mask_local' | 'summary_sources' | 'log_retention_days'
>;

export function AiSettingsPage() {
  const t = useLabel();
  // A read-only licence: the switches show the state but change nothing (coverage §17 item 3).
  const { writable } = useLicence();
  const { can } = useAccess();
  const { modal, message } = App.useApp();
  const settings = useAiSettings(can('ai.manage'));
  const save = useSaveAiSettings();
  useTenantChannel((m) => {
    if (m.type === 'ai.settings_changed') void settings.refetch();
  });
  const saved = settings.data;
  // Template E (D-147): this page has a form field (retention days), so every setting on it,
  // the switches too, goes through the one save bar; nothing applies on its own.
  const values = useMemo<Draft>(
    () => ({
      enabled: saved?.enabled ?? false,
      disabled_features: saved?.disabled_features ?? [],
      mask_local: saved?.mask_local ?? false,
      summary_sources: saved?.summary_sources ?? [],
      log_retention_days: saved?.log_retention_days ?? 30,
    }),
    [saved],
  );
  const { draft, set, changes, changed, discard } = useSettingsDraft(values);

  if (!can('ai.manage')) return <NoAccess titleKey="nav.admin_ai" />;
  if (saved === undefined) return null;

  const send = () => {
    save.mutate(
      { body: changed, version: saved.version },
      {
        onSuccess: () => void message.success(t('ai_settings.saved')),
        onError: reportError,
      },
    );
  };
  // What this save switches off: asked first, saying what happens to results already made
  // (REQ-AI-027); switching on, masking and the rest save without a question.
  const turningOff = [
    ...(saved.enabled && !draft.enabled ? [t('ai_settings.master')] : []),
    ...draft.disabled_features
      .filter((code) => !saved.disabled_features.includes(code))
      .map((code) => t(`ai_feature.${code}`)),
  ];
  const onSave = () => {
    if (turningOff.length === 0) {
      send();
      return;
    }
    modal.confirm({
      title:
        turningOff.length === 1 && saved.enabled && !draft.enabled
          ? t('ai_settings.confirm_master_off')
          : t('ai_settings.confirm_off', { feature: turningOff.join(', ') }),
      content: t('ai_settings.off_effect'),
      okText: t('ai_settings.switch_off'),
      okButtonProps: { danger: true },
      cancelText: t('actions.cancel'),
      onOk: send,
    });
  };

  return (
    <div data-testid="ai-settings">
      <SettingsCard title={t('ai_settings.title')} testId="ai-card-master">
        <Row
          id="ai-master"
          label={t('ai_settings.master')}
          help={t('ai_settings.master_help')}
          control={
            <Switch
              checked={draft.enabled}
              disabled={!writable}
              aria-labelledby="ai-master"
              data-testid="ai-master"
              onChange={(on) => {
                set({ enabled: on });
              }}
            />
          }
        />
      </SettingsCard>
      <SettingsCard title={t('ai_settings.features')} testId="ai-card-features">
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          {AREAS.map((area) => {
            const features = saved.features.filter((f) => f.area === area);
            if (features.length === 0) return null;
            return (
              <section key={area} aria-labelledby={`ai-area-${area}`}>
                <Typography.Title level={4} id={`ai-area-${area}`} style={{ fontSize: 14 }}>
                  {t(`ai_area.${area}`)}
                </Typography.Title>
                <Space direction="vertical" style={{ width: '100%' }}>
                  {features.map((feature) => {
                    const off = draft.disabled_features.includes(feature.code);
                    return (
                      <Row
                        key={feature.code}
                        id={`ai-feature-${feature.code}`}
                        label={t(`ai_feature.${feature.code}`)}
                        control={
                          <Switch
                            checked={!off}
                            disabled={!draft.enabled || !writable}
                            aria-labelledby={`ai-feature-${feature.code}`}
                            data-testid={`ai-feature-${feature.code}`}
                            onChange={(on) => {
                              set({
                                disabled_features: on
                                  ? draft.disabled_features.filter((c) => c !== feature.code)
                                  : [...draft.disabled_features, feature.code],
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
      </SettingsCard>
      <SettingsCard title={t('ai_settings.privacy')} testId="ai-card-privacy">
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
                  checked={draft.mask_local}
                  disabled={!writable}
                  aria-labelledby="ai-mask-local"
                  data-testid="ai-mask-local"
                  onChange={(on) => {
                    set({ mask_local: on });
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
                value={draft.summary_sources}
                disabled={!writable}
                aria-labelledby="ai-summary-sources"
                data-testid="ai-summary-sources"
                options={SUMMARY_SOURCES.map((code) => ({
                  value: code,
                  label: t(`ai_summary_source.${code}`),
                  disabled: draft.summary_sources.length === 1 && draft.summary_sources[0] === code,
                }))}
                onChange={(next) => {
                  if (next.length > 0) set({ summary_sources: next });
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
              // Wraps as a whole: at 390 px the unit never breaks one letter a line (QA9-V-11).
              <Space wrap>
                <InputNumber
                  min={1}
                  max={365}
                  value={draft.log_retention_days}
                  disabled={!writable}
                  onChange={(value) => {
                    if (value !== null) set({ log_retention_days: value });
                  }}
                  aria-labelledby="ai-retention"
                  data-testid="ai-retention"
                />
                <Typography.Text style={{ whiteSpace: 'nowrap' }}>
                  {t('ai_settings.days')}
                </Typography.Text>
              </Space>
            }
          />
        </Space>
      </SettingsCard>
      <StickySaveBar
        changes={changes}
        saving={save.isPending}
        onDiscard={discard}
        onSave={onSave}
      />
    </div>
  );
}
