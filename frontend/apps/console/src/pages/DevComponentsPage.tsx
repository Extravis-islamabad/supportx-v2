import { App, Button, Card, Space, Typography } from 'antd';
import { useMemo } from 'react';

import { ApiError } from '@supportx/api-client';
import { Chart } from '@supportx/charts';
import { AppearanceControls, reportError, useLabel, WriteButton } from '@supportx/ui';

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri'] as const;
const COUNTS = [12, 19, 7, 15, 9];

/** Sample problems, shaped like real API answers, to preview each error message. */
function sample(code: string, status: number, params: Record<string, string> = {}): ApiError {
  return new ApiError(
    status,
    {
      type: `urn:supportx:problem:${code}`,
      title: code,
      status,
      code,
      message_key: `errors.${code}`,
      params,
      errors: [],
    },
    crypto.randomUUID(),
  );
}

const SAMPLES = [
  ['entitlement_required', sample('entitlement_required', 403, { feature: 'cmdb' })],
  ['read_only_mode', sample('read_only_mode', 403, { reason: 'expired' })],
  ['technician_limit_reached', sample('technician_limit_reached', 403)],
  ['version_conflict', sample('version_conflict', 409)],
  ['network_error', new ApiError(0, null, crypto.randomUUID(), 'network')],
] as const;

/**
 * Development-only gallery (route exists only when import.meta.env.DEV): theme controls, the
 * chart wrapper, the read-only aware button and every error toast.
 */
// Held open (duration 0): the toast contrast check scans them fully shown, never mid-animation.
const TOASTS = ['success', 'error', 'warning', 'info'] as const;

export function DevComponentsPage() {
  const t = useLabel();
  const { message } = App.useApp();
  const option = useMemo(
    () => ({
      xAxis: { type: 'category', data: DAYS.map((day) => t(`weekday.${day}`)) },
      yAxis: { type: 'value' },
      series: [{ type: 'bar', data: COUNTS }],
    }),
    [t],
  );
  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Title level={1}>{t('dev.title')}</Typography.Title>
      <Card>
        <AppearanceControls />
      </Card>
      <Card title={t('dev.chart_title')}>
        <Chart option={option} ariaLabel={t('dev.chart_aria')} />
      </Card>
      <Card>
        <WriteButton type="primary">{t('dev.write_button')}</WriteButton>
      </Card>
      <Card>
        <Button
          onClick={() => {
            for (const type of TOASTS) {
              void message.open({ type, content: t('dev.toast_sample'), duration: 0 });
            }
          }}
          data-testid="dev-toasts"
        >
          {t('dev.toasts')}
        </Button>
      </Card>
      <Card title={t('dev.errors')}>
        <Space wrap>
          {SAMPLES.map(([key, error]) => (
            <Button
              key={key}
              onClick={() => {
                reportError(error);
              }}
            >
              {t(error.messageKey)}
            </Button>
          ))}
        </Space>
      </Card>
    </Space>
  );
}
