import { Alert, App, Button, Card, Flex, Input, Space, Typography } from 'antd';
import { useEffect, useState } from 'react';

import {
  ApiError,
  loginUrl,
  useOpenSupportLink,
  type SupportLinkOpened,
} from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

import { capturedToken, forgetCapturedToken, tenantSlug } from './supportLink';

function retryAfter(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.status !== 429) return null;
  const seconds = Number(error.problem?.params?.retry_after_seconds ?? '');
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : 60;
}

/**
 * The engineer's page behind the mailed link (D-177): one POST spends the link and shows the
 * temporary password once. Every failure reads the same (used, expired, wrong, revoked). No
 * other request is made before or after, so success and failure cost the same (lane B (5)).
 */
export function SupportStartPage() {
  const t = useLabel();
  const { message } = App.useApp();
  const open = useOpenSupportLink();
  const [token] = useState(capturedToken);
  const [opened, setOpened] = useState<SupportLinkOpened | null>(null);
  const [failed, setFailed] = useState(false);
  const [waitSeconds, setWaitSeconds] = useState<number | null>(null);

  useEffect(() => {
    forgetCapturedToken(); // the page holds it; the module keeps no copy
    return () => {
      // Leaving the page: the password goes with it, from the state and the mutation (lane B (3)).
      setOpened(null);
      open.reset();
    };
    // The reset must run once, on unmount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const spend = () => {
    if (token === null) return;
    setFailed(false);
    setWaitSeconds(null);
    open.mutate(
      { token, tenant: tenantSlug() },
      {
        onSuccess: (result) => {
          setOpened(result);
          open.reset(); // the answer lives in this page's state only
        },
        onError: (error) => {
          const wait = retryAfter(error);
          if (wait !== null) setWaitSeconds(wait);
          else setFailed(true);
        },
      },
    );
  };

  return (
    <Flex justify="center" style={{ padding: 16, minHeight: '100vh' }} data-testid="support-start">
      <Card style={{ maxWidth: 520, width: '100%', alignSelf: 'flex-start', marginTop: 48 }}>
        <Flex vertical gap={16}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {t('vendor_support.start.title')}
          </Typography.Title>
          {token === null && opened === null && (
            <Alert type="info" showIcon message={t('vendor_support.start.no_link')} />
          )}
          {token !== null && opened === null && (
            <>
              <Typography.Paragraph style={{ margin: 0 }}>
                {t('vendor_support.start.intro')}
              </Typography.Paragraph>
              {failed && (
                <Alert
                  type="error"
                  showIcon
                  message={t('vendor_support.start.failed')}
                  data-testid="support-start-failed"
                />
              )}
              {waitSeconds !== null && (
                <Alert
                  type="warning"
                  showIcon
                  message={t('vendor_support.start.rate_limited', { seconds: waitSeconds })}
                  data-testid="support-start-wait"
                />
              )}
              <Button
                type="primary"
                loading={open.isPending}
                disabled={failed}
                onClick={spend}
                data-testid="support-start-open"
              >
                {t('vendor_support.start.open')}
              </Button>
            </>
          )}
          {opened !== null && (
            <Space
              direction="vertical"
              style={{ width: '100%' }}
              data-testid="support-start-opened"
            >
              <label htmlFor="support-start-login">{t('vendor_support.start.login')}</label>
              <Input id="support-start-login" readOnly value={opened.login} dir="ltr" />
              <label htmlFor="support-start-password">{t('vendor_support.start.password')}</label>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  id="support-start-password"
                  readOnly
                  value={opened.password}
                  dir="ltr"
                  style={{ fontFamily: 'monospace' }}
                  data-testid="support-start-password"
                />
                <Button
                  onClick={() => {
                    // On click only (lane B (4)); nothing promises to clear the clipboard.
                    void navigator.clipboard
                      .writeText(opened.password)
                      .then(() => void message.success(t('vendor_support.password.copied')));
                  }}
                  data-testid="support-start-copy"
                >
                  {t('vendor_support.password.copy')}
                </Button>
              </Space.Compact>
              <Typography.Text type="secondary">{t('vendor_support.start.after')}</Typography.Text>
              <Button
                type="primary"
                href={loginUrl('console', '/')}
                onClick={() => {
                  setOpened(null);
                }}
                data-testid="support-start-sign-in"
              >
                {t('vendor_support.start.sign_in')}
              </Button>
            </Space>
          )}
        </Flex>
      </Card>
    </Flex>
  );
}
