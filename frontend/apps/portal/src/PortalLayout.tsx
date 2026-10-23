import { Layout, Menu } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router';

import { useLogout, useSession } from '@supportx/api-client';
import type { LabelKey } from '@supportx/labels';
import { AppHeader, ConnectivityBanner, LicenceBanners, useLabel } from '@supportx/ui';

const NAV: { path: string; labelKey: LabelKey }[] = [
  { path: '/', labelKey: 'nav.home' },
  { path: '/requests', labelKey: 'nav.my_requests' },
  { path: '/catalog', labelKey: 'nav.catalog' },
];

/** Portal frame: one header with a simple top navigation; no sidebar, no command palette. */
export function PortalLayout() {
  const t = useLabel();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const session = useSession().data;
  const logout = useLogout();
  if (session === undefined || session === null) return null;
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <AppHeader appName="app.portal.name" session={session} onLogout={() => void logout()} />
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
      <Layout.Content
        id="main"
        style={{ padding: 32, maxWidth: 1100, width: '100%', marginInline: 'auto' }}
      >
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}
