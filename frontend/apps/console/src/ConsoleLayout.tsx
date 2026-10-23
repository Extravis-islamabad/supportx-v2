import { App as AntApp } from 'antd';
import { useCallback, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';

import { useLogout, useSession, useSwitchTenant } from '@supportx/api-client';
import {
  AppHeader,
  AppShell,
  CommandPalette,
  ConnectivityBanner,
  LicenceBanners,
  useCommandPaletteShortcut,
  useLabel,
  useLicence,
  visibleNav,
} from '@supportx/ui';

import { NAV } from './nav';

/** Console frame: sidebar, header (tenant switcher, user menu), banners, command palette. */
export function ConsoleLayout() {
  const t = useLabel();
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const session = useSession().data;
  const logout = useLogout();
  const switchTenant = useSwitchTenant();
  const licence = useLicence();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const openPalette = useCallback(() => {
    setPaletteOpen(true);
  }, []);
  useCommandPaletteShortcut(openPalette);

  const nav = useMemo(() => visibleNav(NAV, licence), [licence]);
  const commands = useMemo(
    () => [
      ...nav
        .filter((item) => !item.locked)
        .map((item) => ({ key: item.key, title: t(item.labelKey), path: item.path })),
      { key: 'profile', title: t('nav.profile'), path: '/profile' },
    ],
    [nav, t],
  );
  const section = pathname.split('/')[1] ?? '';
  const activeKey = section === '' ? 'home' : section;

  if (session === undefined || session === null) return null; // SessionGate renders only with one

  return (
    <AppShell
      nav={nav}
      activeKey={activeKey}
      onNavigate={(path) => void navigate(path)}
      header={
        <AppHeader
          appName="app.console.name"
          session={session}
          onLogout={() => void logout()}
          onProfile={() => void navigate('/profile')}
          onOpenPalette={openPalette}
          switchingTenant={switchTenant.isPending}
          onSwitchTenant={(tenantId) => {
            switchTenant.mutate(tenantId, {
              onSuccess: (me) => {
                void message.success(t('auth.tenant_switched', { tenant: me.tenant.name }));
                void navigate('/');
              },
            });
          }}
        />
      }
      banners={
        <>
          <ConnectivityBanner />
          <LicenceBanners />
        </>
      }
    >
      <Outlet />
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        commands={commands}
        onNavigate={(path) => void navigate(path)}
      />
    </AppShell>
  );
}
