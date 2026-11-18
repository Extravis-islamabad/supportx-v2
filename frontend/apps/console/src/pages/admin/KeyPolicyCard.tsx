import { App, Button, Flex, Form, InputNumber, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  useIdentitySettings,
  useKeyPolicyImpact,
  useSaveIdentitySettings,
  type KeyPolicyDraft,
} from '@supportx/api-client';
import { FormProblem, SettingsCard, useFormProblem, useLabel, useLicence } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';

const LIFETIME = { min: 1, max: 366 };
const UNUSED = { min: 7, max: 365 };

/**
 * The key policy (WP-057 S4a, REQ-SEC-037): how long new keys may last, whether they must name
 * their addresses, and when an unused key is listed. Keys made before a stricter policy are
 * flagged and listed, never revoked; the card says how many before it is saved (the
 * coordinator, 2026-11-16).
 */
export function KeyPolicyCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const { writable } = useLicence();
  const settings = useIdentitySettings();
  const save = useSaveIdentitySettings();
  const problem = useFormProblem();
  const [draft, setDraft] = useState<KeyPolicyDraft>();
  const saved = settings.data;
  const current: KeyPolicyDraft | undefined =
    draft ??
    (saved === undefined
      ? undefined
      : {
          key_max_lifetime_days: saved.key_max_lifetime_days,
          keys_require_ip_range: saved.keys_require_ip_range,
          allow_non_expiring_keys: saved.allow_non_expiring_keys,
          key_unused_days: saved.key_unused_days,
        });
  const asked = useDebounced(current, 300);
  const impact = useKeyPolicyImpact(asked);
  if (saved === undefined || current === undefined) return null;
  const changed =
    draft !== undefined &&
    (draft.key_max_lifetime_days !== saved.key_max_lifetime_days ||
      draft.keys_require_ip_range !== saved.keys_require_ip_range ||
      draft.key_unused_days !== saved.key_unused_days);
  const set = (next: Partial<KeyPolicyDraft>) => {
    problem.clear();
    setDraft({ ...current, ...next });
  };
  const flagged = impact.data?.keys ?? 0;
  return (
    <SettingsCard title={t('api_keys.policy.title')} testId="api-key-policy">
      <Form layout="vertical" disabled={!writable}>
        <Typography.Paragraph type="secondary">{t('api_keys.policy.help')}</Typography.Paragraph>
        <Flex gap={24} wrap>
          <Form.Item
            label={t('api_keys.policy.max_lifetime')}
            htmlFor="api-key-policy-lifetime"
            help={t('api_keys.policy.days_help', LIFETIME)}
          >
            <InputNumber
              id="api-key-policy-lifetime"
              min={LIFETIME.min}
              max={LIFETIME.max}
              precision={0}
              value={current.key_max_lifetime_days}
              onChange={(value) => {
                if (typeof value === 'number') set({ key_max_lifetime_days: value });
              }}
              data-testid="api-key-policy-lifetime"
            />
          </Form.Item>
          <Form.Item
            label={t('api_keys.policy.unused_after')}
            htmlFor="api-key-policy-unused"
            help={t('api_keys.policy.days_help', UNUSED)}
          >
            <InputNumber
              id="api-key-policy-unused"
              min={UNUSED.min}
              max={UNUSED.max}
              precision={0}
              value={current.key_unused_days}
              onChange={(value) => {
                if (typeof value === 'number') set({ key_unused_days: value });
              }}
              data-testid="api-key-policy-unused"
            />
          </Form.Item>
        </Flex>
        <Flex gap={8} align="center">
          <Switch
            checked={current.keys_require_ip_range}
            aria-labelledby="api-key-policy-ip-label"
            onChange={(value) => {
              set({ keys_require_ip_range: value });
            }}
            data-testid="api-key-policy-ip"
          />
          <Typography.Text id="api-key-policy-ip-label">
            {t('api_keys.policy.require_ip')}
          </Typography.Text>
        </Flex>
        {changed && (
          <Typography.Paragraph
            type={flagged > 0 ? 'warning' : 'secondary'}
            style={{ marginTop: 16 }}
            data-testid="api-key-policy-impact"
            role="status"
          >
            {flagged > 0
              ? t('api_keys.policy.impact', { count: flagged })
              : t('api_keys.policy.impact_none')}
          </Typography.Paragraph>
        )}
        <FormProblem problem={problem} />
        <Flex justify="end" gap={8}>
          <Button
            disabled={!changed}
            onClick={() => {
              setDraft(undefined);
              problem.clear();
            }}
            data-testid="api-key-policy-reset"
          >
            {t('actions.cancel')}
          </Button>
          <Button
            type="primary"
            disabled={!changed}
            loading={save.isPending}
            onClick={() => {
              save.mutate(
                {
                  body: {
                    key_max_lifetime_days: current.key_max_lifetime_days,
                    keys_require_ip_range: current.keys_require_ip_range,
                    key_unused_days: current.key_unused_days,
                  },
                  version: saved.version,
                },
                {
                  onSuccess: () => {
                    setDraft(undefined);
                    void message.success(t('api_keys.settings.saved'));
                  },
                  onError: (error) => problem.show(error),
                },
              );
            }}
            data-testid="api-key-policy-save"
          >
            {t('actions.save')}
          </Button>
        </Flex>
      </Form>
    </SettingsCard>
  );
}
