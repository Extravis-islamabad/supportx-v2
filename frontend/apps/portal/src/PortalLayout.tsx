import { Flex, Layout, Menu, Typography } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router';

import { useLogout, useSession, useSetUiLocale } from '@supportx/api-client';
import type { LabelKey } from '@supportx/labels';
import {
  AnnouncementBanners,
  AppHeader,
  BrandLogo,
  brandText,
  ConnectivityBanner,
  LicenceBanners,
  reportError,
  useAppearance,
  useLabel,
  useLicence,
} from '@supportx/ui';

const NAV: { path: string; labelKey: LabelKey }[] = [
  { path: '/', labelKey: 'nav.home' },
  { path: '/requests', labelKey: 'nav.my_requests' },
  { path: '/catalog', labelKey: 'nav.catalog' },
];

/** Portal frame: one header with a simple top navigation; no sidebar, no command palette. */
export function PortalLayout() {
  const t = useLabel();
  const { branding, locale } = useAppearance();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const session = useSession().data;
  const logout = useLogout();
  const licence = useLicence();
  const setUiLocale = useSetUiLocale(session?.user.id ?? '');
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
        onLogout={() => void logout()}
        onLocaleChange={(locale) => {
          setUiLocale.mutate(locale, { onError: reportError });
        }}
      />
      <nav aria-label={t('nav.main')}>
        <Menu
          mode="horizontal"
          selectedKeys={[pathname]}
          items={NAV.map((item) => ({
            key: item.path,
            label: t(item.labelKey),
            onClick: () => void navigate(item.path),
          }))}
        />
      </nav>
      <ConnectivityBanner />
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
