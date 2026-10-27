import { App, Button, Card, Flex, List, Space, Typography } from 'antd';
import { useEffect } from 'react';

import { accountActionUrl, useAccountSecurity, type AccountAction } from '@supportx/api-client';

import { useLabel } from './appearance';
import { useDateTime } from './dates';
import { ToneTag } from './ToneTag';

const ACTIONS: AccountAction[] = ['password', 'mfa', 'recovery_codes'];
const STATUSES = ['success', 'cancelled', 'error'] as const;

/** Keycloak's result of a change started here, from the return address; then tidied away. */
function useActionResult() {
  const t = useLabel();
  const { message } = App.useApp();
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const action = params.get('account_action') as AccountAction | null;
    const status = params.get('status') as (typeof STATUSES)[number] | null;
    if (action === null || !ACTIONS.includes(action) || status === null) return;
    if (!STATUSES.includes(status)) return;
    if (status === 'success') void message.success(t(`account.done.${action}`));
    else if (status === 'cancelled') void message.info(t('account.cancelled'));
    else void message.error(t('account.failed'));
    params.delete('account_action');
    params.delete('status');
    const query = params.toString();
    window.history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : ''));
  }, [message, t]);
}

/**
 * My account's sign-in and security (WP-039 session 3, REQ-SEC-028): opens without an emailed
 * code (AC1). Changes happen on the sign-in service's own pages, which ask for the current
 * password first (AC2); the password never passes through SupportX.
 */
export function AccountSecurityCard({
  returnTo = window.location.pathname,
}: {
  /** Where to come back after the sign-in service's page: this page by default. */
  returnTo?: string;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const security = useAccountSecurity();
  useActionResult();
  if (security.data === undefined) return <Card loading data-testid="account-security" />;
  const found = security.data;
  const go = (action: AccountAction) => accountActionUrl(action, returnTo);
  const mfaTag = found.mfa_enrolled ? (
    <ToneTag tone="success" testId="account-mfa-state">
      {t('account.mfa.on')}
    </ToneTag>
  ) : found.mfa_due_at !== null ? (
    <ToneTag tone="warning" testId="account-mfa-state">
      {t('account.mfa.due', { date: dates.format(found.mfa_due_at) })}
    </ToneTag>
  ) : (
    <ToneTag tone="default" testId="account-mfa-state">
      {t('account.mfa.off')}
    </ToneTag>
  );
  return (
    <Card title={t('account.title')} data-testid="account-security">
      <Flex vertical gap={20}>
        <Flex vertical gap={8}>
          <Typography.Text strong>{t('account.password')}</Typography.Text>
          {found.has_password ? (
            <div>
              <Button href={go('password')} data-testid="account-change-password">
                {t('account.change_password')}
              </Button>
            </div>
          ) : (
            <Typography.Text type="secondary">{t('account.sso_only')}</Typography.Text>
          )}
        </Flex>
        <Flex vertical gap={8}>
          <Space wrap>
            <Typography.Text strong>{t('account.mfa.title')}</Typography.Text>
            {mfaTag}
          </Space>
          <Typography.Text type="secondary">
            {t(`account.mfa.policy.${found.mfa_mode}`)}
          </Typography.Text>
          <Space wrap>
            {found.mfa_mode !== 'off' || found.mfa_enrolled ? (
              <Button
                type={found.mfa_enrolled ? 'default' : 'primary'}
                href={go('mfa')}
                data-testid="account-set-up-mfa"
              >
                {t(found.mfa_enrolled ? 'account.mfa.another' : 'account.mfa.set_up')}
              </Button>
            ) : null}
            {found.mfa_enrolled && (
              <Button href={go('recovery_codes')} data-testid="account-recovery-codes">
                {t(found.recovery_codes ? 'account.recovery.new' : 'account.recovery.get')}
              </Button>
            )}
          </Space>
          {found.mfa_enrolled && !found.recovery_codes && (
            <Typography.Text type="warning">{t('account.recovery.missing')}</Typography.Text>
          )}
        </Flex>
        <Flex vertical gap={8}>
          <Typography.Text strong>{t('account.recent')}</Typography.Text>
          {!found.details_available ? (
            <Typography.Text type="secondary">{t('account.details_unavailable')}</Typography.Text>
          ) : (
            <List
              size="small"
              dataSource={found.recent_sign_ins}
              locale={{ emptyText: t('account.recent_none') }}
              data-testid="account-recent"
              renderItem={(item) => (
                <List.Item>
                  <Space wrap>
                    <span>{dates.format(item.at)}</span>
                    <ToneTag tone={item.outcome === 'success' ? 'success' : 'error'}>
                      {t(`sign_in_outcome.${item.outcome}`)}
                    </ToneTag>
                    <Typography.Text type="secondary">
                      {t(`sign_in_method.${item.method}`)}
                    </Typography.Text>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </Flex>
      </Flex>
    </Card>
  );
}
