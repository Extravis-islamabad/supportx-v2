import { Navigate, Outlet, useLocation, useNavigate } from 'react-router';

import { NoAccess, PageHeader, SectionNav, useAccess, useLabel, usePageCrumbs } from '@supportx/ui';

/** Admin tabs, each shown only to users holding its permission (WP-016). */
const TABS = [
  { key: 'users', labelKey: 'nav.admin_users', permission: 'users.view' },
  { key: 'organization', labelKey: 'nav.admin_organization', permission: 'sites.view' },
  { key: 'roles', labelKey: 'nav.admin_roles', permission: 'roles.view' },
  { key: 'incidents', labelKey: 'nav.admin_incidents', permission: 'settings.manage' },
  { key: 'requests', labelKey: 'nav.admin_requests', permission: 'settings.manage' },
  { key: 'automation', labelKey: 'nav.admin_automation', permission: 'automation.view' },
  { key: 'sla', labelKey: 'nav.admin_sla', permission: 'sla.view' },
  { key: 'audit', labelKey: 'nav.audit', permission: 'audit.view' },
  { key: 'files', labelKey: 'nav.admin_files', permission: 'files.manage' },
  { key: 'branding', labelKey: 'nav.admin_branding', permission: 'branding.manage' },
  { key: 'security', labelKey: 'nav.admin_security', permission: 'identity.manage' },
  { key: 'ai', labelKey: 'nav.admin_ai', permission: 'ai.manage' },
  { key: 'api-keys', labelKey: 'nav.admin_api_keys', permission: 'api_keys.manage' },
  { key: 'notifications', labelKey: 'nav.admin_notifications', permission: 'notifications.manage' },
  { key: 'mail', labelKey: 'nav.admin_mail', permission: 'integrations.manage_email' },
  { key: 'integrations', labelKey: 'nav.admin_integrations', permission: 'integrations.view' },
  // Knowledge settings or its article types (D-120): either permission opens the tab.
  {
    key: 'knowledge',
    labelKey: 'nav.admin_knowledge',
    permission: 'knowledge.manage_settings',
    also: 'knowledge.manage_types',
  },
] as const;

export function AdminLayout() {
  const t = useLabel();
  const { can } = useAccess();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const tabs = TABS.filter((tab) => can(tab.permission) || ('also' in tab && can(tab.also)));
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
      <PageHeader title={t('nav.admin')} testId="admin-header" />
      <SectionNav
        label={t('nav.admin')}
        active={active}
        onNavigate={(path) => void navigate(path)}
        items={tabs.map((tab) => ({
          key: tab.key,
          label: t(tab.labelKey),
          path: `/admin/${tab.key}`,
        }))}
        testId="admin-sections"
      />
      <Outlet />
    </>
  );
}
