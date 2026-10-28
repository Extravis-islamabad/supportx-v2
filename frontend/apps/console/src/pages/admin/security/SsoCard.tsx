import { useListFormat } from '@supportx/labels';
import { App, Button, Card, Descriptions, Flex, List, Modal, Space, Spin, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';

import {
  useRemoveSso,
  useSsoProviders,
  useSsoTestResult,
  useStartSsoTest,
  useSwitchSso,
  type SsoProvider,
} from '@supportx/api-client';
import {
  ConflictDialog,
  reportError,
  ToneTag,
  useConflict,
  useDateTime,
  useLabel,
  WriteButton,
  type Tone,
} from '@supportx/ui';

import { ssoView, useSsoFieldName } from './conflict';

import { SsoEditor } from './SsoEditor';

const SLOW_TEST_MS = 60_000;
const STATE_TONE: Record<SsoProvider['state'], Tone> = {
  draft: 'default',
  tested: 'info',
  on: 'success',
  off: 'warning',
};

/**
 * A test sign-in (REQ-SEC-007/008: test before switching on), in a private window: this browser is
 * signed in to the sign-in service as the admin, and it never signs a second person in where
 * someone already is (it refuses, and would leave a half-made account behind). The admin opens
 * the link in a private window and signs in there as a person of the organisation; the result
 * shows here as it comes. No SupportX session and no person are created by the test.
 */
function TestDialog({ provider, onClose }: { provider: SsoProvider; onClose: () => void }) {
  const t = useLabel();
  const start = useStartSsoTest();
  const [testId, setTestId] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const result = useSsoTestResult(provider.id, testId);
  // Some refusals (a SAML answer whose signature does not match the certificate) leave no trace
  // the screen can read: the other window shows the sign-in service's reason. Said after a while.
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (testId === null) return;
    const timer = window.setTimeout(() => {
      setSlow(true);
    }, SLOW_TEST_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [testId]);
  // One test per opening of the dialog (React's development double effect would start two,
  // and the link shown would not be the one polled).
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    start.mutate(provider.id, {
      onSuccess: (started) => {
        setTestId(started.test_id);
        setUrl(started.url);
      },
      onError: (error) => {
        reportError(error);
        onClose();
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- start once, when opened
  }, []);
  const found = result.data;
  return (
    <Modal
      open
      title={t('security.sso.test_title', { name: provider.display_name })}
      onCancel={onClose}
      footer={<Button onClick={onClose}>{t('actions.close')}</Button>}
      data-testid="sso-test-dialog"
    >
      <Flex vertical gap={12} role="status">
        {url !== null && found?.status !== 'passed' && (
          <Flex vertical gap={8}>
            <Typography.Text>{t('security.sso.test_private')}</Typography.Text>
            <Typography.Text copyable={{ text: url }} strong data-testid="sso-test-link">
              {t('security.sso.test_link')}
            </Typography.Text>
            <Space>
              <Spin size="small" />
              <Typography.Text type="secondary">{t('security.sso.test_pending')}</Typography.Text>
            </Space>
            {slow && found?.status === 'pending' && (
              <Typography.Text data-testid="sso-test-slow">
                {t('security.sso.test_slow')}
              </Typography.Text>
            )}
          </Flex>
        )}
        {found?.status === 'passed' && (
          <>
            <ToneTag tone="success" testId="sso-test-passed">
              {t('security.sso.test_passed')}
            </ToneTag>
            <Descriptions
              size="small"
              column={1}
              items={[
                {
                  key: 'email',
                  label: t('security.sso.map.email'),
                  children: found.identity?.email ?? '',
                },
                {
                  key: 'name',
                  label: t('security.sso.test_name'),
                  children: found.identity?.name ?? '',
                },
                {
                  key: 'department',
                  label: t('security.sso.map.department'),
                  children: found.identity?.department ?? t('security.sso.test_not_sent'),
                },
                {
                  key: 'site',
                  label: t('security.sso.map.site'),
                  children: found.identity?.site ?? t('security.sso.test_not_sent'),
                },
              ]}
            />
            <Typography.Text type="secondary">{t('security.sso.test_next')}</Typography.Text>
          </>
        )}
        {found?.status === 'failed' && (
          <Flex vertical gap={4}>
            <ToneTag tone="error" testId="sso-test-failed">
              {t('security.sso.test_failed')}
            </ToneTag>
            <Typography.Text>{t(`sso_test.${found.reason ?? 'provider_error'}`)}</Typography.Text>
          </Flex>
        )}
      </Flex>
    </Modal>
  );
}

/**
 * Single sign-on set-ups of the tenant (WP-039; REQ-SEC-007, REQ-SEC-008): each starts in
 * draft, is tested with a real sign-in, then switched on (shown on the tenant's sign-in page).
 */
export function SsoCard() {
  const t = useLabel();
  const list = useListFormat();
  const dates = useDateTime();
  const { modal } = App.useApp();
  const providers = useSsoProviders();
  const switching = useSwitchSso();
  const remove = useRemoveSso();
  const [editing, setEditing] = useState<SsoProvider | 'new' | null>(null);
  const [testing, setTesting] = useState<SsoProvider | null>(null);
  const items = providers.data?.items ?? [];
  // A set-up another admin changed first (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflict();
  const ssoField = useSsoFieldName();
  const [tried, setTried] = useState<{ provider: SsoProvider; act: 'switch' | 'remove' }>();
  const live = items.find((p) => p.id === tried?.provider.id);
  const failed = (provider: SsoProvider, act: 'switch' | 'remove') => (error: unknown) => {
    if (conflict.take(error)) setTried({ provider, act });
    else reportError(error);
  };
  const switchOver = (provider: SsoProvider, version = provider.version) => {
    switching.mutate(
      { id: provider.id, on: provider.state !== 'on', version },
      { onError: failed(provider, 'switch') },
    );
  };
  const removeIt = (provider: SsoProvider, version = provider.version) =>
    remove.mutateAsync({ id: provider.id, version }).catch(failed(provider, 'remove'));

  return (
    <Card
      title={t('security.sso.title')}
      data-testid="security-sso"
      extra={
        <WriteButton
          onClick={() => {
            setEditing('new');
          }}
          data-testid="sso-add"
        >
          {t('security.sso.add')}
        </WriteButton>
      }
    >
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.sso.intro')}
        </Typography.Paragraph>
        <List
          loading={providers.isLoading}
          dataSource={items}
          locale={{
            emptyText: <Typography.Text type="secondary">{t('security.sso.none')}</Typography.Text>,
          }}
          renderItem={(provider) => (
            <List.Item
              data-testid={`sso-${provider.display_name}`}
              actions={[
                <WriteButton
                  key="test"
                  size="small"
                  disabled={provider.state === 'off'}
                  onClick={() => {
                    setTesting(provider);
                  }}
                  data-testid="sso-test"
                >
                  {t('security.sso.test')}
                </WriteButton>,
                <WriteButton
                  key="switch"
                  size="small"
                  type={provider.state === 'on' ? 'default' : 'primary'}
                  disabled={provider.state !== 'on' && provider.tested_at == null}
                  loading={switching.isPending && switching.variables.id === provider.id}
                  onClick={() => {
                    switchOver(provider);
                  }}
                  data-testid="sso-switch"
                >
                  {t(
                    provider.state === 'on' ? 'security.sso.switch_off' : 'security.sso.switch_on',
                  )}
                </WriteButton>,
                <WriteButton
                  key="edit"
                  size="small"
                  onClick={() => {
                    setEditing(provider);
                  }}
                  data-testid="sso-edit"
                >
                  {t('actions.edit')}
                </WriteButton>,
                <WriteButton
                  key="remove"
                  size="small"
                  danger
                  onClick={() => {
                    modal.confirm({
                      title: t('security.sso.remove_title', { name: provider.display_name }),
                      content: t('security.sso.remove_body'),
                      okText: t('actions.delete'),
                      okButtonProps: { danger: true },
                      cancelText: t('actions.cancel'),
                      onOk: () => removeIt(provider),
                    });
                  }}
                  data-testid="sso-remove"
                >
                  {t('actions.delete')}
                </WriteButton>,
              ]}
            >
              <Flex vertical gap={4} style={{ minWidth: 0 }}>
                <Space wrap>
                  <Typography.Text strong>{provider.display_name}</Typography.Text>
                  <ToneTag tone="default">{t(`sso_preset.${provider.preset}`)}</ToneTag>
                  <ToneTag tone={STATE_TONE[provider.state]} testId="sso-state">
                    {t(`sso_state.${provider.state}`)}
                  </ToneTag>
                </Space>
                <Typography.Text type="secondary">
                  {t('security.sso.domains_list', {
                    domains: list(provider.domains),
                  })}
                </Typography.Text>
                {provider.tested_at != null && (
                  <Typography.Text type="secondary">
                    {t('security.sso.tested_at', { when: dates.format(provider.tested_at) })}
                  </Typography.Text>
                )}
                {(provider.last_check?.problems ?? []).map((code) => (
                  <div key={code}>
                    <ToneTag tone="warning">{t(`sso_check.${code}`)}</ToneTag>
                  </div>
                ))}
                <Typography.Text type="secondary">
                  {t(
                    provider.protocol === 'saml'
                      ? 'security.sso.sp_metadata'
                      : 'security.sso.redirect_uri',
                  )}{' '}
                  <Typography.Text code copyable>
                    {provider.protocol === 'saml'
                      ? provider.service_provider_metadata_url
                      : provider.redirect_uri}
                  </Typography.Text>
                </Typography.Text>
              </Flex>
            </List.Item>
          )}
        />
      </Flex>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={ssoField}
        opened={ssoView(tried?.provider)}
        latest={ssoView(live)}
        onReload={() => {
          conflict.clear();
          setTried(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (tried !== undefined) {
            const version = conflict.latestVersion ?? live?.version;
            if (tried.act === 'remove') void removeIt(tried.provider, version);
            else switchOver(tried.provider, version);
          }
          setTried(undefined);
        }}
      />
      {editing !== null && (
        <SsoEditor
          open
          provider={editing === 'new' ? null : editing}
          latest={
            editing === 'new' ? undefined : providers.data?.items.find((p) => p.id === editing.id)
          }
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
      {testing !== null && (
        <TestDialog
          provider={testing}
          onClose={() => {
            setTesting(null);
          }}
        />
      )}
    </Card>
  );
}
