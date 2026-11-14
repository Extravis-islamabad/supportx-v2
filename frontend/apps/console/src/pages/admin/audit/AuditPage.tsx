import { Space } from 'antd';
import { useSearchParams } from 'react-router';

import { NoAccess, useAccess, useLabel, Tabs } from '@supportx/ui';

import { ArchivesTab } from './ArchivesTab';
import { AuditAlertBanner } from './AuditAlertBanner';
import { AuditLogTab } from './AuditLogTab';
import { AuditSettingsTab } from './AuditSettingsTab';
import { ExportsTab } from './ExportsTab';
import { IntegrityTab } from './IntegrityTab';
import { PersonalDataAccessTab } from './PersonalDataAccessTab';
import { SignInsTab } from './SignInsTab';

const TABS = [
  'log',
  'sign_ins',
  'personal_access',
  'integrity',
  'exports',
  'archives',
  'settings',
] as const;
type Tab = (typeof TABS)[number];

/**
 * Admin › Audit log (WP-018, REQ-AUD-001 to 010): the log, its integrity, exports for auditors,
 * archives past retention and the settings. Auditors read, search, export and verify; only `audit.manage` changes
 * settings; nobody can change an entry.
 */
export function AuditPage() {
  const t = useLabel();
  const { can } = useAccess();
  const [params, setParams] = useSearchParams();
  // The sign-in log has its own right (WP-057 S1a): someone may hold it without audit.view.
  const signIns = can('identity.view_sign_ins');
  // Who accessed personal data (REQ-AUD-017) has its own right too: a DPO may hold only it.
  const personalAccess = can('audit.view_personal_data_access');
  if (!can('audit.view') && !signIns && !personalAccess) {
    return <NoAccess titleKey="nav.audit" />;
  }
  const visible = TABS.filter((tab) => {
    if (tab === 'sign_ins') return signIns;
    if (tab === 'personal_access') return personalAccess;
    return can('audit.view') && (tab !== 'exports' || can('audit.export'));
  });
  const requested = params.get('tab') as Tab | null;
  const fallback: Tab = visible[0] ?? 'log';
  const active: Tab = requested !== null && visible.includes(requested) ? requested : fallback;
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <AuditAlertBanner showLink={false} />
      <Tabs
        activeKey={active}
        onChange={(key) => {
          const next = new URLSearchParams(params);
          next.set('tab', key);
          next.delete('entry');
          setParams(next);
        }}
        items={visible.map((tab) => ({ key: tab, label: t(`audit.ui.tab.${tab}`) }))}
        data-testid="audit-tabs"
      />
      {active === 'log' && <AuditLogTab />}
      {active === 'sign_ins' && <SignInsTab />}
      {active === 'personal_access' && <PersonalDataAccessTab />}
      {active === 'integrity' && <IntegrityTab />}
      {active === 'exports' && <ExportsTab />}
      {active === 'archives' && <ArchivesTab />}
      {active === 'settings' && <AuditSettingsTab />}
    </Space>
  );
}
