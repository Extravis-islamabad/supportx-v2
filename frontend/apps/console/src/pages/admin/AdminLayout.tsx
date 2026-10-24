import { Tabs, Typography } from 'antd';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router';

import { NoAccess, useAccess, useLabel } from '@supportx/ui';

/** Admin tabs, each shown only to users holding its permission (WP-016). */
const TABS = [
  { key: 'users', labelKey: 'nav.admin_users', permission: 'users.view' },
  { key: 'roles', labelKey: 'nav.admin_roles', permission: 'roles.view' },
  { key: 'audit', labelKey: 'nav.audit', permission: 'audit.view' },
] as const;

export function AdminLayout() {
  const t = useLabel();
  const { can } = useAccess();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const tabs = TABS.filter((tab) => can(tab.permission));
  const active = pathname.split('/')[2];
  const first = tabs[0];

  if (first === undefined) return <NoAccess titleKey="nav.admin" />;
  if (active === undefined || active === '') return <Navigate to={`/admin/${first.key}`} replace />;

  return (
    <>
      <Typography.Title level={1}>{t('nav.admin')}</Typography.Title>
      <Tabs
        activeKey={active}
        onChange={(key) => void navigate(`/admin/${key}`)}
        items={tabs.map((tab) => ({ key: tab.key, label: t(tab.labelKey) }))}
      />
      <Outlet />
    </>
  );
}
