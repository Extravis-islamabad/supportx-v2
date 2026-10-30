import { Tabs, Typography } from 'antd';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router';

import { NoAccess, useAccess, useLabel, usePageCrumbs } from '@supportx/ui';

/** Admin tabs, each shown only to users holding its permission (WP-016). */
const TABS = [
  { key: 'users', labelKey: 'nav.admin_users', permission: 'users.view' },
  { key: 'organization', labelKey: 'nav.admin_organization', permission: 'sites.view' },
  { key: 'roles', labelKey: 'nav.admin_roles', permission: 'roles.view' },
  { key: 'incidents', labelKey: 'nav.admin_incidents', permission: 'settings.manage' },
  { key: 'automation', labelKey: 'nav.admin_automation', permission: 'automation.view' },
  { key: 'audit', labelKey: 'nav.audit', permission: 'audit.view' },
  { key: 'files', labelKey: 'nav.admin_files', permission: 'files.manage' },
  { key: 'branding', labelKey: 'nav.admin_branding', permission: 'branding.manage' },
  { key: 'security', labelKey: 'nav.admin_security', permission: 'identity.manage' },
  { key: 'notifications', labelKey: 'nav.admin_notifications', permission: 'notifications.manage' },
  { key: 'mail', labelKey: 'nav.admin_mail', permission: 'mailboxes.manage' },
] as const;

export function AdminLayout() {
  const t = useLabel();
  const { can } = useAccess();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const tabs = TABS.filter((tab) => can(tab.permission));
  const active = pathname.split('/')[2];
  const first = tabs[0];
  const tab = tabs.find((candidate) => candidate.key === active);
  usePageCrumbs(
    tab === undefined
      ? null
      : [{ label: t('nav.admin'), path: '/admin' }, { label: t(tab.labelKey) }],
  );

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
