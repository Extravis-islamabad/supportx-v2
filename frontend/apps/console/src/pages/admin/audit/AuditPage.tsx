import { Space, Tabs } from 'antd';
import { useSearchParams } from 'react-router';

import { NoAccess, useAccess, useLabel } from '@supportx/ui';

import { AuditAlertBanner } from './AuditAlertBanner';
import { AuditLogTab } from './AuditLogTab';
import { AuditSettingsTab } from './AuditSettingsTab';
import { ExportsTab } from './ExportsTab';
import { IntegrityTab } from './IntegrityTab';

const TABS = ['log', 'integrity', 'exports', 'settings'] as const;
type Tab = (typeof TABS)[number];

/**
 * Admin › Audit log (WP-018, REQ-AUD-001 to 010): the log, its integrity, exports for auditors
 * and the settings. Auditors read, search, export and verify; only `audit.manage` changes
 * settings; nobody can change an entry.
 */
export function AuditPage() {
  const t = useLabel();
  const { can } = useAccess();
  const [params, setParams] = useSearchParams();
  if (!can('audit.view')) return <NoAccess titleKey="nav.audit" />;
  const visible = TABS.filter((tab) => tab !== 'exports' || can('audit.export'));
  const requested = params.get('tab') as Tab | null;
  const active: Tab = requested !== null && visible.includes(requested) ? requested : 'log';
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
      {active === 'integrity' && <IntegrityTab />}
      {active === 'exports' && <ExportsTab />}
      {active === 'settings' && <AuditSettingsTab />}
    </Space>
  );
}
