import { Alert, Button, Card, Flex, Result, Skeleton, Typography } from 'antd';
import { useState } from 'react';

import { ApiError, usePeekNotifyLink, useStopNotifyLink } from '@supportx/api-client';
import { describeError, useLabel } from '@supportx/ui';

import { linkTenant, useFragmentToken } from './publicLink';

/**
 * Stop the e-mails an address kept informed gets about one record (WP-046a S6; REQ-INC-066),
 * without signing in. A confirmation first: opening the link changes nothing (mail scanners
 * follow links); only the button stops them, once (lane B's terms). The address is shown masked.
 */
export function StopMailsPage() {
  const t = useLabel();
  const token = useFragmentToken();
  const [tenant] = useState(linkTenant);
  const peek = usePeekNotifyLink(token, tenant);
  const stop = useStopNotifyLink();
  const [done, setDone] = useState(false);
  const gone = <Result status="info" title={t('kept_informed.stop.gone')} />;

  // Only the server's "this link does not work" means the link is dead; an outage or a lost
  // connection keeps the person's chance to try again (lane C's #485 review).
  const dead = (error: unknown) => error instanceof ApiError && error.status === 404;
  const failed = (error: unknown) =>
    error instanceof ApiError ? describeError(error, t).title : t('errors.internal_error');

  let content;
  if (token === undefined || dead(peek.error) || dead(stop.error)) {
    content = <div data-testid="stop-mails-gone">{gone}</div>;
  } else if (peek.error !== null) {
    content = (
      <Flex vertical gap={12} align="start" data-testid="stop-mails-failed">
        <Alert type="error" showIcon message={failed(peek.error)} />
        <Button onClick={() => void peek.refetch()}>{t('actions.retry')}</Button>
      </Flex>
    );
  } else if (peek.isLoading || peek.data === undefined) {
    content = <Skeleton active />;
  } else {
    const named = { id: peek.data.display_id, address: peek.data.address };
    content = done ? (
      <div data-testid="stop-mails-done">
        <Result status="success" title={t('kept_informed.stop.done', named)} />
      </div>
    ) : (
      <Card>
        <Flex vertical gap={16} align="start">
          <Typography.Text data-testid="stop-mails-ask">
            {t('kept_informed.stop.ask', named)}
          </Typography.Text>
          {stop.error !== null && (
            // Not a dead link: the button stays for another try.
            <Alert
              type="error"
              showIcon
              message={failed(stop.error)}
              data-testid="stop-mails-failed"
            />
          )}
          <Button
            type="primary"
            danger
            loading={stop.isPending}
            onClick={() => {
              stop.mutate(
                { token, tenant },
                {
                  onSuccess: () => {
                    setDone(true);
                  },
                },
              );
            }}
            data-testid="stop-mails-button"
          >
            {t('kept_informed.stop.button')}
          </Button>
        </Flex>
      </Card>
    );
  }
  return (
    <main>
      <Flex vertical gap={16} style={{ maxWidth: 640, margin: '48px auto', padding: '0 16px' }}>
        <Typography.Title level={1}>{t('kept_informed.stop.title')}</Typography.Title>
        {content}
      </Flex>
    </main>
  );
}
