import { DownOutlined, SearchOutlined, UserOutlined } from '@ant-design/icons';
import { Avatar, Button, Dropdown, Flex, Layout, Popover, Select, Typography, theme } from 'antd';
import type { ReactNode } from 'react';

import type { MeResponse } from '@supportx/api-client';
import type { LabelKey } from '@supportx/labels';

import { useLabel } from '../appearance';
import { AppearanceControls } from '../AppearanceControls';

export interface AppHeaderProps {
  /** Labels key of the app's name, e.g. `app.console.name`. */
  appName: LabelKey;
  session: MeResponse;
  onLogout: () => void;
  /** Tenant switcher; omitted = no switcher (single tenant, or the portal). */
  onSwitchTenant?: (tenantId: string) => void;
  switchingTenant?: boolean;
  onProfile?: () => void;
  onOpenPalette?: () => void;
  extra?: ReactNode;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join('')
    .toUpperCase();
}

/** Top bar: search (command palette), appearance, tenant (switcher), user menu. */
export function AppHeader({
  appName,
  session,
  onLogout,
  onSwitchTenant,
  switchingTenant = false,
  onProfile,
  onOpenPalette,
  extra,
}: AppHeaderProps) {
  const t = useLabel();
  const { token } = theme.useToken();
  const canSwitch = onSwitchTenant !== undefined && session.tenants.length > 1;

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
        {t(appName)}
      </Typography.Text>
      {onOpenPalette !== undefined && (
        <Button icon={<SearchOutlined />} onClick={onOpenPalette} data-testid="open-palette">
          {t('palette.open')} <Typography.Text keyboard>{t('palette.shortcut')}</Typography.Text>
        </Button>
      )}
      {extra}
      <Popover content={<AppearanceControls />} trigger="click" placement="bottomRight">
        <Button data-testid="appearance-menu">{t('appearance.title')}</Button>
      </Popover>
      {canSwitch ? (
        <Select
          data-testid="tenant-switcher"
          aria-label={t('auth.switch_tenant')}
          value={session.tenant.id}
          loading={switchingTenant}
          disabled={switchingTenant}
          onChange={onSwitchTenant}
          options={session.tenants.map((tenant) => ({ value: tenant.id, label: tenant.name }))}
          style={{ minWidth: 180 }}
          labelRender={() => <span data-testid="tenant-name">{session.tenant.name}</span>}
        />
      ) : (
        <Typography.Text data-testid="tenant-name" type="secondary">
          {session.tenant.name}
        </Typography.Text>
      )}
      <Dropdown
        trigger={['click']}
        menu={{
          items: [
            ...(onProfile === undefined
              ? []
              : [
                  {
                    key: 'profile',
                    icon: <UserOutlined />,
                    label: t('nav.profile'),
                    onClick: onProfile,
                  },
                ]),
            { key: 'logout', label: t('auth.sign_out'), onClick: onLogout, danger: true },
          ],
        }}
      >
        <Button type="text" data-testid="user-menu" style={{ height: 'auto', paddingBlock: 4 }}>
          <Flex align="center" gap={8}>
            <Avatar aria-hidden style={{ background: token.colorPrimary }}>
              {initials(session.user.display_name)}
            </Avatar>
            <Typography.Text data-testid="user-name">{session.user.display_name}</Typography.Text>
            <DownOutlined aria-hidden />
          </Flex>
        </Button>
      </Dropdown>
    </Layout.Header>
  );
}
