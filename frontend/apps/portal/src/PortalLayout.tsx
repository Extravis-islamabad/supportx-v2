import { useQueryClient } from '@tanstack/react-query';
import { Flex, Layout, Menu, Typography } from 'antd';
import { Outlet, useLocation, useMatches, useNavigate } from 'react-router';

import { clearAllKeptDrafts } from '@supportx/forms';
import {
  catalogKeys,
  portalSettingsKey,
  useLogout,
  useSession,
  useSetUiLocale,
  type Feature,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import type { LabelKey } from '@supportx/labels';
import {
  AnnouncementBanners,
  AppHeader,
  BrandLogo,
  brandText,
  useDocumentTitle,
  ConnectivityBanner,
  LicenceBanners,
  MfaReminder,
  reportError,
  useAppearance,
  useLabel,
  useLicence,
} from '@supportx/ui';

const NAV: { path: string; labelKey: LabelKey; feature?: Feature }[] = [
  { path: '/', labelKey: 'nav.home' },
  { path: '/requests', labelKey: 'nav.my_requests' },
  // WP-030 D9: the requester's service requests, and approvals waiting for them (a requester can be an approver, REQ-SR-022 AC2).
  {
    path: '/service-requests',
    labelKey: 'portal.service_requests.title',
    feature: 'service_request',
  },
  { path: '/approvals', labelKey: 'portal.approvals.title', feature: 'service_request' },
  { path: '/catalog', labelKey: 'nav.catalog' },
];

/** The menu entry of a path: its own, or the area it lies in (`/requests/…` is My requests). */
function selected(pathname: string): string {
  const area = NAV.find((item) => item.path !== '/' && pathname.startsWith(`${item.path}/`));
  return area?.path ?? pathname;
}

/** Portal frame: one header with a simple top navigation; no sidebar, no command palette. */
export function PortalLayout() {
  const t = useLabel();
  const { branding, locale } = useAppearance();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  // The browser tab names the page, then the portal (QA9-F-07): the deepest route's title.
  const titleKey = useMatches()
    .map((m) => (m.handle as { titleKey?: LabelKey } | undefined)?.titleKey)
    .filter((k): k is LabelKey => k !== undefined)
    .at(-1);
  useDocumentTitle(
    titleKey === undefined ? [] : [{ label: t(titleKey) }],
    brandText(branding, 'portalName', locale) ?? t('app.portal.name'),
  );
  const session = useSession().data;
  const logout = useLogout();
  const licence = useLicence();
  const setUiLocale = useSetUiLocale(session?.user.id ?? '');
  // The catalog changed (WP-031: an item published or retired, a category, the settings): the
  // catalog pages refetch what the requester may see, live (§8).
  const queryClient = useQueryClient();
  useTenantChannel((event) => {
    if (event.type === 'service_catalog.changed') {
      void queryClient.invalidateQueries({ queryKey: catalogKeys.all });
    }
    // WP-032 D8: a portal setting changed: open portals take it at once (REQ-PRT-031 AC2).
    if (event.type === 'work_items.portal_settings_changed') {
      void queryClient.invalidateQueries({ queryKey: portalSettingsKey });
    }
  });
  if (session === undefined || session === null) return null;
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <AppHeader
        appName="app.portal.name"
        session={session}
        start={
          <Flex align="center" gap={12} style={{ flex: 1, minWidth: 0 }}>
            <BrandLogo height={28} />
            <Typography.Text type="secondary" ellipsis data-testid="portal-name">
              {brandText(branding, 'portalName', locale) ?? t('app.portal.name')}
            </Typography.Text>
          </Flex>
        }
        onProfile={() => void navigate('/account')}
        onLogout={() => {
          clearAllKeptDrafts(); // an explicit sign-out: the next person at this computer starts clean
          void logout();
        }}
        onLocaleChange={(locale) => {
          setUiLocale.mutate(locale, { onError: reportError });
        }}
      />
      <nav aria-label={t('nav.main')}>
        <Menu
          mode="horizontal"
          selectedKeys={[selected(pathname)]}
          items={NAV.filter((item) => !item.feature || licence.has(item.feature)).map((item) => ({
            key: item.path,
            label: t(item.labelKey),
            onClick: () => void navigate(item.path),
          }))}
        />
      </nav>
      <ConnectivityBanner />
      {pathname !== '/account' && <MfaReminder />}
      <LicenceBanners />
      {/* The full text is on the home page; banners there would only repeat it. */}
      {pathname !== '/' && (
        <AnnouncementBanners enabled={licence.has('incident')} onOpen={() => void navigate('/')} />
      )}
      <Layout.Content
        id="main"
        style={{ padding: 32, maxWidth: 1100, width: '100%', marginInline: 'auto' }}
      >
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}
