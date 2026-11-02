import { useQueryClient } from '@tanstack/react-query';
import { App as AntApp } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';

import {
  queryKeys,
  readPending,
  useLogout,
  useSetFormDensity,
  useSession,
  useSetNavLayout,
  useSetUiLocale,
  useSwitchTenant,
} from '@supportx/api-client';
import { clearAllKeptDrafts } from '@supportx/forms';
import {
  AnnouncementBanners,
  AppHeader,
  AppShell,
  brandText,
  CommandPalette,
  HeaderCrumbs,
  ConnectivityBanner,
  MfaReminder,
  LicenceBanners,
  reportError,
  useCommandPaletteShortcut,
  useAccess,
  useAppearance,
  useCurrentCrumbs,
  useDocumentTitle,
  useLabel,
  useLicence,
  visibleNav,
} from '@supportx/ui';
import { useTenantChannel } from '@supportx/realtime';

import { AvailabilitySwitch } from './AvailabilitySwitch';
import { EventDeliveryBanner } from './EventDeliveryBanner';
import { NotificationBell } from './notifications/NotificationBell';
import { NotificationsBanner } from './notifications/NotificationsBanner';
import { useAvailabilityItem } from './useAvailabilityItem';
import { TechnicianVisibilityQuestion } from './pages/admin/TechnicianVisibility';
import { AuditAlertBanner } from './pages/admin/audit/AuditAlertBanner';
import { LoopBanner } from './pages/admin/automation/LoopBanner';
import { FilesBanner } from './pages/admin/files/FilesBanner';
import { usePaletteIncidents } from './pages/incidents/usePaletteIncidents';

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
  const [paletteQuery, setPaletteQuery] = useState('');
  const openPalette = useCallback(() => {
    setPaletteOpen(true);
  }, []);
  useCommandPaletteShortcut(openPalette);

  // Incident settings changed by an admin anywhere (WP-020c): every open form, list and record
  // reloads its pick lists, labels and templates; nothing waits for a page refresh (§8).
  const queryClient = useQueryClient();
  useTenantChannel((event) => {
    // Custom fields changed (WP-026): forms, records, lists and filters reload them.
    // Sites, groups, departments or desks changed (WP-021): pickers, lists and the admin pages.
    if (event.type === 'organization.structure_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.organization.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.access.all });
      return;
    }
    // Rules, routing, auto-assignment or someone's availability changed (WP-029).
    if (event.type === 'automation.changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.automation.all });
      // A stopped loop also shows on the record's automation panel.
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.incidents.all, 'history'] });
      return;
    }
    if (event.type === 'metadata.custom_fields_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customFields.all });
      return;
    }
    if (event.type !== 'work_items.settings_changed') return;
    for (const key of [
      queryKeys.incidents.catalogue,
      queryKeys.incidents.categories,
      queryKeys.incidents.templates,
    ]) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  });

  const setNavLayout = useSetNavLayout(session?.user.id ?? '');
  const setUiLocale = useSetUiLocale(session?.user.id ?? '');
  const setFormDensity = useSetFormDensity(session?.user.id ?? '');
  // Technicians' Available / Away in the user menu below 1200 px (WP-029).
  const availabilityItems = useAvailabilityItem(
    session?.user.id ?? '',
    session?.user.user_type === 'technician' && licence.has('incident'),
  );
  // Preferences chosen just before a reload, whose save had not finished: applied and sent
  // again, so a quick reload never loses them (the flaky QA BUG-04 test was this race).
  const userId = session?.user.id;
  useEffect(() => {
    if (userId === undefined) return;
    const pending = readPending(userId);
    if (pending.ui_locale !== undefined) setUiLocale.mutate(pending.ui_locale);
    if (pending.nav_layout !== undefined) {
      setNavLayout.mutate(pending.nav_layout as Parameters<typeof setNavLayout.mutate>[0]);
    }
    if (pending.form_density !== undefined) {
      setFormDensity.mutate(pending.form_density as Parameters<typeof setFormDensity.mutate>[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per signed-in user
  }, [userId]);
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
  const paletteRecords = usePaletteIncidents(
    paletteOpen,
    paletteQuery,
    session?.user.id ?? null,
    access.can('incidents.view') && licence.has('incident'),
  );
  const section = pathname.split('/')[1] ?? '';
  const activeKey = section === '' ? 'home' : section;
  // Where the user is (2026-10-28): the page's own crumbs, else its section; the tab says it too.
  const sectionItem = NAV.find((item) => item.key === activeKey);
  const sectionCrumbs = useMemo(
    () =>
      sectionItem === undefined
        ? section === 'profile'
          ? [{ label: t('nav.profile') }]
          : []
        : [{ label: t(sectionItem.labelKey), path: sectionItem.path }],
    [sectionItem, section, t],
  );
  const crumbs = useCurrentCrumbs(sectionCrumbs);
  const { branding, locale } = useAppearance();
  useDocumentTitle(crumbs, brandText(branding, 'productName', locale) ?? t('product.name'));

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
          context={(narrow) => (
            <HeaderCrumbs
              crumbs={crumbs}
              narrow={narrow}
              onNavigate={(path) => void navigate(path)}
            />
          )}
          onNavLayoutChange={(layout) => {
            setNavLayout.mutate(layout, { onError: reportError });
          }}
          onLocaleChange={(locale) => {
            setUiLocale.mutate(locale, { onError: reportError });
          }}
          onLogout={() => {
            clearAllKeptDrafts(); // an explicit sign-out: the next person at this computer starts clean
            void logout();
          }}
          onProfile={() => void navigate('/profile')}
          onOpenPalette={openPalette}
          menuItems={availabilityItems}
          extra={
            <>
              <NotificationBell />
              {session.user.user_type === 'technician' && licence.has('incident') && (
                <AvailabilitySwitch userId={session.user.id} />
              )}
            </>
          }
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
          <EventDeliveryBanner />
          {pathname !== '/profile' && <MfaReminder />}
          <LicenceBanners />
          <AuditAlertBanner />
          <LoopBanner />
          <FilesBanner />
          <NotificationsBanner />
          <TechnicianVisibilityQuestion />
          <AnnouncementBanners
            enabled={licence.has('incident')}
            onOpen={(id) => void navigate(`/announcements/${id}`)}
          />
        </>
      }
    >
      {session.user.nav_layout === 'top' && crumbs.length > 1 && (
        // The top menu shows the section; a record or sub-page says where it is above the page.
        <div style={{ marginBlockEnd: 12 }}>
          <HeaderCrumbs crumbs={crumbs} narrow={false} onNavigate={(path) => void navigate(path)} />
        </div>
      )}
      <Outlet />
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        commands={commands}
        onNavigate={(path) => void navigate(path)}
        onQueryChange={setPaletteQuery}
        records={paletteRecords}
      />
    </AppShell>
  );
}
