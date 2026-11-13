import { Button, Card, Flex, Result, Skeleton, Typography } from 'antd';
import { useState } from 'react';

import { usePeekNotifyLink, useStopNotifyLink } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

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

  let content;
  if (token === undefined || peek.error !== null || stop.error !== null) {
    content = <div data-testid="stop-mails-gone">{gone}</div>;
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
    <Flex vertical gap={16} style={{ maxWidth: 640, margin: '48px auto', padding: '0 16px' }}>
      <Typography.Title level={1}>{t('kept_informed.stop.title')}</Typography.Title>
      {content}
    </Flex>
  );
}
