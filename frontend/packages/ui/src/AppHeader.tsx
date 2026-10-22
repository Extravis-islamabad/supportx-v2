import { Avatar, Button, Flex, Layout, Typography, theme } from 'antd';
import type { ReactNode } from 'react';

import type { MeResponse } from '@supportx/api-client';
import type { LabelKey } from '@supportx/labels';

import { useLabel } from './appearance';

export interface AppHeaderProps {
  /** Labels key of the app's name, e.g. `app.console.name`. */
  appName: LabelKey;
  session: MeResponse;
  onLogout: () => void;
  extra?: ReactNode;
}

/** Top bar: app name, the signed-in user, their organisation and a sign-out button. */
export function AppHeader({ appName, session, onLogout, extra }: AppHeaderProps) {
  const t = useLabel();
  const initials = session.user.display_name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join('')
    .toUpperCase();

  const { token } = theme.useToken();

  return (
    <Layout.Header
      role="banner"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        paddingInline: 24,
        background: token.colorBgContainer,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        lineHeight: 'normal',
      }}
    >
      <Typography.Text strong style={{ flex: 1 }}>
        {t('product.name')} · {t(appName)}
      </Typography.Text>
      {extra}
      <Flex align="center" gap={12}>
        <Avatar aria-hidden style={{ background: token.colorPrimary }}>
          {initials}
        </Avatar>
        <Flex vertical>
          <Typography.Text data-testid="user-name">{session.user.display_name}</Typography.Text>
          <Typography.Text data-testid="tenant-name" type="secondary" style={{ fontSize: 12 }}>
            {session.tenant.name}
          </Typography.Text>
        </Flex>
        <Button onClick={onLogout}>{t('auth.sign_out')}</Button>
      </Flex>
    </Layout.Header>
  );
}
