import { App, Button, Space, Typography } from 'antd';
import { useEffect, type ReactNode } from 'react';

import { ApiError } from '@supportx/api-client';

import { useLabel } from '../appearance';
import { CopyReference } from './CopyReference';
import { describeError } from './describe';
import { setErrorReporter } from './reporter';

/**
 * Shows reported errors as translated notifications: real failures with a "Copy reference"
 * action, expected refusals (4xx with a reason) as a plain notice. Network
 * outages are reported once per outage (the reconnecting banner takes over from there).
 */
export function ErrorReporterProvider({ children }: { children: ReactNode }) {
  const { notification } = App.useApp();
  const t = useLabel();

  useEffect(() => {
    let outageShown = false;
    setErrorReporter((error) => {
      if (error instanceof ApiError && error.isOutage) {
        if (outageShown) return;
        outageShown = true;
        setTimeout(() => (outageShown = false), 30_000);
      }
      const { title, detail, reference } = describeError(error, t);
      // An expected refusal the screen did not show itself: a plain notice in the user's
      // language, not an error with a support reference (QA WP-029 BUG-02).
      if (error instanceof ApiError && error.isRefusal) {
        notification.warning({
          message: title,
          description: detail,
          placement: 'topRight',
          role: 'status',
        });
        return;
      }
      notification.error({
        message: title,
        description:
          detail === undefined && reference === null ? undefined : (
            <Space direction="vertical" size={4}>
              {detail !== undefined && <Typography.Text>{detail}</Typography.Text>}
              {reference !== null && <CopyReference reference={reference} />}
            </Space>
          ),
        placement: 'topRight',
        role: 'alert',
      });
    });
    return () => {
      setErrorReporter(null);
    };
  }, [notification, t]);

  return <>{children}</>;
}

/** Retry button used in inline error states. */
export function RetryButton({ onRetry }: { onRetry: () => void }) {
  const t = useLabel();
  return <Button onClick={onRetry}>{t('actions.retry')}</Button>;
}
