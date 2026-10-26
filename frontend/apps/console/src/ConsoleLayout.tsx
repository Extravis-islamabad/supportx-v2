import { App as AntApp } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';

import {
  useLogout,
  useSession,
  useSetNavLayout,
  useSetUiLocale,
  useSwitchTenant,
} from '@supportx/api-client';
import {
  AnnouncementBanners,
  AppHeader,
  AppShell,
  CommandPalette,
  ConnectivityBanner,
  LicenceBanners,
  reportError,
  useCommandPaletteShortcut,
  useAccess,
  useLabel,
  useLicence,
  visibleNav,
} from '@supportx/ui';

import { AuditAlertBanner } from './pages/admin/audit/AuditAlertBanner';
import { FilesBanner } from './pages/admin/files/FilesBanner';

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

  const setNavLayout = useSetNavLayout(session?.user.id ?? '');
  const setUiLocale = useSetUiLocale(session?.user.id ?? '');
  // A new page starts at its top, as a link would (QA BUG-17: a new record opened scrolled).
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);
  const access = useAccess();
  const nav = useMemo(
    () =>
      visibleNav(NAV, { canAny: access.canAny, has: licence.has, managesLicence: licence.isAdmin }),
    [access, licence],
  );
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
      layout={session.user.nav_layout}
      onNavigate={(path) => void navigate(path)}
      header={(topNav) => (
        <AppHeader
          appName="app.console.name"
          session={session}
          start={topNav ?? undefined}
          onNavLayoutChange={(layout) => {
            setNavLayout.mutate(layout, { onError: reportError });
          }}
          onLocaleChange={(locale) => {
            setUiLocale.mutate(locale, { onError: reportError });
          }}
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
      )}
      banners={
        <>
          <ConnectivityBanner />
          <LicenceBanners />
          <AuditAlertBanner />
          <FilesBanner />
          <AnnouncementBanners
            enabled={licence.has('incident')}
            onOpen={(id) => void navigate(`/announcements/${id}`)}
          />
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
