import { Card, Flex, Form, Input, InputNumber, Select, Switch, Typography } from 'antd';
import { useState } from 'react';

import type { AssetAgeBasis, AssetSettings, AssetSettingsInput } from '@supportx/api-client';
import { lengthLimit, useLabel, WriteButton } from '@supportx/ui';

import { Problems } from '../incidents/shared';
import { useCatalogueSave } from './shared';

const AGE_BASES: AssetAgeBasis[] = ['acquisition_date', 'created_date'];
type Toggle =
  | 'cost_includes_tax'
  | 'site_follows_owner'
  | 'portal_own_assets_only'
  | 'email_include_assets'
  | 'portal_booking';
const TOGGLES: Toggle[] = [
  'cost_includes_tax',
  'site_follows_owner',
  'portal_own_assets_only',
  'email_include_assets',
  'portal_booking', // WP-049b s1, REQ-AST-032 AC3: off by default
];

/**
 * The tenant's asset settings. Only what the admin changed is sent, with the version the form
 * started from; another admin's save in between is refused (409), the settings refetch and the
 * form shows them, never writing over that change.
 */
export function SettingsTab({ settings }: { settings: AssetSettings }) {
  const t = useLabel();
  const { run, problems, pending } = useCatalogueSave();
  const [draft, setDraft] = useState<{ body: AssetSettingsInput; version: number }>();
  const body = draft?.body ?? {};
  const edit = (next: AssetSettingsInput) => {
    setDraft({ body: { ...body, ...next }, version: draft?.version ?? settings.version });
  };
  const value = <K extends keyof AssetSettingsInput>(key: K) =>
    (body[key] ?? settings[key as keyof AssetSettings]) as NonNullable<AssetSettingsInput[K]>;
  const dirty = Object.entries(body).some(([key, v]) => v !== settings[key as keyof AssetSettings]);
  return (
    <Card title={t('assets.admin.settings')} data-testid="asset-settings">
      <Problems problems={problems} testId="asset-settings-problems" />
      <Form
        layout="vertical"
        style={{ maxWidth: 640 }}
        onFinish={() => {
          if (draft === undefined) return;
          const reset = () => {
            setDraft(undefined);
          };
          // A conflict drops the draft too: the form then shows the other admin's saved values.
          run({ kind: 'settings', version: draft.version, body: draft.body }, reset, reset);
        }}
      >
        <Form.Item
          label={t('assets.admin.tag_pattern')}
          htmlFor="asset-tag-pattern"
          extra={<Typography.Text type="secondary">{t('assets.admin.tag_help')}</Typography.Text>}
        >
          <Input
            id="asset-tag-pattern"
            dir="ltr"
            count={lengthLimit(40)}
            value={value('tag_pattern')}
            onChange={(event) => {
              edit({ tag_pattern: event.target.value });
            }}
            style={{ maxWidth: 240 }}
            data-testid="asset-tag-pattern"
          />
        </Form.Item>
        <Form.Item label={t('assets.admin.age_basis')} htmlFor="asset-age-basis">
          <Select
            id="asset-age-basis"
            aria-label={t('assets.admin.age_basis')}
            value={value('age_basis')}
            onChange={(next: AssetAgeBasis) => {
              edit({ age_basis: next });
            }}
            options={AGE_BASES.map((code) => ({
              value: code,
              label: t(`asset_age_basis.${code}`),
            }))}
            style={{ maxWidth: 240 }}
            data-testid="asset-age-basis"
          />
        </Form.Item>
        <Flex gap={24} wrap>
          <Form.Item label={t('assets.admin.copy_limit')} htmlFor="asset-copy-limit">
            <InputNumber
              id="asset-copy-limit"
              min={1}
              max={500}
              value={value('copy_limit')}
              onChange={(next) => {
                if (next !== null) edit({ copy_limit: next });
              }}
              data-testid="asset-copy-limit"
            />
          </Form.Item>
          <Form.Item label={t('assets.admin.scan_retention')} htmlFor="asset-scan-retention">
            <InputNumber
              id="asset-scan-retention"
              min={1}
              max={60}
              value={value('scan_retention_months')}
              onChange={(next) => {
                if (next !== null) edit({ scan_retention_months: next });
              }}
              data-testid="asset-scan-retention"
            />
          </Form.Item>
          {/* REQ-AST-059 AC2: how far ahead the managers hear a warranty is ending (Appendix A). */}
          <Form.Item label={t('assets.admin.warranty_notice')} htmlFor="asset-warranty-notice">
            <InputNumber
              id="asset-warranty-notice"
              min={1}
              max={365}
              value={value('warranty_notice_days')}
              onChange={(next) => {
                if (next !== null) edit({ warranty_notice_days: next });
              }}
              data-testid="asset-warranty-notice"
            />
          </Form.Item>
        </Flex>
        {TOGGLES.map((toggle) => (
          <Form.Item
            key={toggle}
            label={t(`assets.admin.${toggle}`)}
            htmlFor={`asset-${toggle}`}
            extra={
              <Typography.Text type="secondary">{t(`assets.admin.${toggle}_help`)}</Typography.Text>
            }
          >
            <Switch
              id={`asset-${toggle}`}
              checked={value(toggle)}
              onChange={(next) => {
                edit({ [toggle]: next });
              }}
              data-testid={`asset-${toggle}`}
            />
          </Form.Item>
        ))}
        <WriteButton
          type="primary"
          htmlType="submit"
          disabled={!dirty}
          loading={pending}
          data-testid="asset-settings-save"
        >
          {t('actions.save')}
        </WriteButton>
      </Form>
    </Card>
  );
}
