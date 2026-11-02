import { Alert, Button, Flex, Typography, theme, type AlertProps } from 'antd';
import { useState, type ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE, TYPE } from '../density';

export interface StripAlert {
  key: string;
  type: NonNullable<AlertProps['type']>;
  message: ReactNode;
  /** A button on the line (reload, set up). */
  action?: ReactNode;
  /** Can be dismissed for this visit (default true). */
  dismissible?: boolean;
  testId?: string;
}

const SEVERITY: Record<StripAlert['type'], number> = { error: 0, warning: 1, info: 2, success: 3 };

/**
 * Alerts as one line (D-124): a single alert is a slim strip; two or more collapse into
 * "3 alerts · View", which opens the list in place. Dismissed alerts stay hidden for this visit.
 */
export function AlertStrip({ alerts, testId }: { alerts: StripAlert[]; testId?: string }) {
  const t = useLabel();
  const { token } = theme.useToken();
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const [open, setOpen] = useState(false);
  const shown = alerts
    .filter((a) => !dismissed.has(a.key))
    .sort((a, b) => SEVERITY[a.type] - SEVERITY[b.type]);
  if (shown.length === 0) return null;

  const strip = (alert: StripAlert) => (
    <Alert
      key={alert.key}
      type={alert.type}
      showIcon
      role="status"
      message={<span style={{ fontSize: TYPE.data }}>{alert.message}</span>}
      action={alert.action}
      closable={alert.dismissible !== false}
      onClose={() => {
        setDismissed((current) => new Set([...current, alert.key]));
      }}
      style={{ paddingBlock: SPACE.xxs, paddingInline: SPACE.sm }}
      data-testid={alert.testId}
    />
  );

  const first = shown[0];
  if (shown.length === 1 && first !== undefined) {
    return (
      <div data-testid={testId} style={{ marginBlock: SPACE.xs }}>
        {strip(first)}
      </div>
    );
  }
  const worst = first?.type ?? 'info';
  return (
    <div data-testid={testId} style={{ marginBlock: SPACE.xs }}>
      <Flex
        align="center"
        gap={SPACE.xs}
        style={{
          paddingBlock: SPACE.xxs,
          paddingInline: SPACE.sm,
          borderRadius: token.borderRadius,
          border: `1px solid ${worst === 'error' ? token.colorErrorBorder : token.colorWarningBorder}`,
          background: worst === 'error' ? token.colorErrorBg : token.colorWarningBg,
        }}
      >
        <Typography.Text style={{ fontSize: TYPE.data }}>
          {t('layout.alerts_count', { count: shown.length })}
        </Typography.Text>
        <Button
          type="link"
          size="small"
          aria-expanded={open}
          onClick={() => {
            setOpen((value) => !value);
          }}
          data-testid={testId === undefined ? undefined : `${testId}-toggle`}
        >
          {open ? t('layout.hide') : t('layout.view')}
        </Button>
      </Flex>
      {open && (
        <Flex vertical gap={SPACE.xxs} style={{ marginTop: SPACE.xxs }}>
          {shown.map(strip)}
        </Flex>
      )}
    </div>
  );
}
