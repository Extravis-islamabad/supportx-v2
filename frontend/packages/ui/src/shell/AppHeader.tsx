import { DownOutlined, SearchOutlined, UserOutlined } from '@ant-design/icons';
import { Avatar, Button, Dropdown, Flex, Layout, Popover, Select, Typography, theme } from 'antd';
import { useSyncExternalStore, type ReactNode } from 'react';

import type { MeResponse, NavLayout } from '@supportx/api-client';
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
  /** Shown instead of the app name at the start of the row (top-bar navigation). */
  start?: ReactNode;
  /** Offer the navigation layout choice (console). */
  onNavLayoutChange?: (layout: NavLayout) => void;
}

/**
 * Whether the Appearance popover is open, kept outside the header component. A layout change
 * renders a different shell tree (the header remounts) and a language change re-renders the
 * whole app; with the popover's own state, the panel and its trigger then disagreed and the
 * first click after the change was lost (WP-014 follow-up). One store, so the popover keeps its
 * state across those re-renders and a single click always toggles it.
 */
let appearanceOpen = false;
const appearanceListeners = new Set<() => void>();

function setAppearanceOpen(open: boolean): void {
  if (open === appearanceOpen) return;
  appearanceOpen = open;
  appearanceListeners.forEach((listener) => {
    listener();
  });
}

function useAppearanceOpen(): boolean {
  return useSyncExternalStore(
    (listener) => {
      appearanceListeners.add(listener);
      return () => appearanceListeners.delete(listener);
    },
    () => appearanceOpen,
  );
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
  start,
  onNavLayoutChange,
}: AppHeaderProps) {
  const t = useLabel();
  const { token } = theme.useToken();
  const canSwitch = onSwitchTenant !== undefined && session.tenants.length > 1;
  const appearanceIsOpen = useAppearanceOpen();

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
      {start ?? (
        <Typography.Text strong style={{ flex: 1 }}>
          {t(appName)}
        </Typography.Text>
      )}
      {onOpenPalette !== undefined && (
        <Button icon={<SearchOutlined />} onClick={onOpenPalette} data-testid="open-palette">
          {t('palette.open')} <Typography.Text keyboard>{t('palette.shortcut')}</Typography.Text>
        </Button>
      )}
      {extra}
      <Popover
        content={
          <AppearanceControls
            navLayout={onNavLayoutChange === undefined ? undefined : session.user.nav_layout}
            onNavLayoutChange={onNavLayoutChange}
          />
        }
        trigger="click"
        placement="bottomRight"
        open={appearanceIsOpen}
        onOpenChange={setAppearanceOpen}
      >
        <Button
          data-testid="appearance-menu"
          aria-expanded={appearanceIsOpen}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setAppearanceOpen(false);
          }}
        >
          {t('appearance.title')}
        </Button>
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
