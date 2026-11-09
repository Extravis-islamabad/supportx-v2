import { App, Card, Flex, Space, Switch, Typography } from 'antd';

import { useIdentitySettings, useSaveIdentitySettings } from '@supportx/api-client';
import { NoAccess, reportError, useAccess, useLabel, useLicence } from '@supportx/ui';

import { ApiKeysPanel } from '../apiKeys/ApiKeysPanel';

// WP-041 (D-128): Admin › API keys. The two tenant rules sit above the list; they are sign-in
// settings, so only whoever may change those (identity.manage) sees them.

function KeyRulesCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useIdentitySettings();
  const save = useSaveIdentitySettings();
  // A read-only licence: the rules are shown, not changeable (the server refuses with 403).
  const { writable } = useLicence();
  if (settings.data === undefined) return null;
  const saved = settings.data;
  const change = (field: 'people_may_create_keys' | 'allow_non_expiring_keys', value: boolean) => {
    save.mutate(
      { body: { [field]: value }, version: saved.version },
      {
        onSuccess: () => void message.success(t('api_keys.settings.saved')),
        onError: reportError,
      },
    );
  };
  const row = (
    field: 'people_may_create_keys' | 'allow_non_expiring_keys',
    label: string,
    help: string,
  ) => (
    <Flex justify="space-between" align="start" gap={16}>
      <Space direction="vertical" size={0}>
        <Typography.Text id={`api-key-rule-${field}`}>{label}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {help}
        </Typography.Text>
      </Space>
      <Switch
        checked={saved[field]}
        loading={save.isPending}
        disabled={!writable}
        aria-labelledby={`api-key-rule-${field}`}
        data-testid={`api-key-rule-${field}`}
        onChange={(value) => {
          change(field, value);
        }}
      />
    </Flex>
  );
  return (
    <Card title={t('api_keys.settings.title')} data-testid="api-key-rules">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {row(
          'people_may_create_keys',
          t('api_keys.settings.people'),
          t('api_keys.settings.people_help'),
        )}
        {row(
          'allow_non_expiring_keys',
          t('api_keys.settings.non_expiring'),
          t('api_keys.settings.non_expiring_help'),
        )}
      </Space>
    </Card>
  );
}

export function ApiKeysPage() {
  const { can } = useAccess();
  if (!can('api_keys.manage')) return <NoAccess titleKey="nav.admin_api_keys" />;
  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {can('identity.manage') && <KeyRulesCard />}
      <ApiKeysPanel mode="admin" />
    </Space>
  );
}
