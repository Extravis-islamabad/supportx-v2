import { Flex, Tabs, Typography } from 'antd';
import { Navigate, useNavigate, useParams } from 'react-router';

import { NoAccess, useAccess, useLabel } from '@supportx/ui';

import { BusinessRulesTab } from './BusinessRulesTab';
import { RoutingTab } from './RoutingTab';

const SECTIONS = ['business-rules', 'routing'] as const;
type Section = (typeof SECTIONS)[number];

/**
 * Admin › Automation (WP-029; ADR-035): business rules and routing and auto-assignment of
 * incidents, for holders of `automation.view` (changes need `automation.manage`). Its own admin
 * section: the incident settings tab bar has no room left (axe, overflow at 1280 px).
 */
export function AutomationPage() {
  const t = useLabel();
  const { can } = useAccess();
  const navigate = useNavigate();
  const { section } = useParams();
  if (!can('automation.view')) return <NoAccess titleKey="nav.admin_automation" />;
  if (section === undefined || !(SECTIONS as readonly string[]).includes(section)) {
    return <Navigate to="/admin/automation/business-rules" replace />;
  }
  const current = section as Section;
  return (
    // minWidth 0: the tab bar fits the screen and folds the rest into "more" (as Incidents).
    <Flex vertical gap={8} style={{ minWidth: 0 }}>
      <Typography.Title level={2}>{t('automation.page_title')}</Typography.Title>
      <Tabs
        activeKey={current}
        onChange={(key) => void navigate(`/admin/automation/${key}`)}
        items={SECTIONS.map((key) => ({ key, label: t(`settings.section.${key}`) }))}
        data-testid="automation-sections"
      />
      {current === 'business-rules' ? <BusinessRulesTab /> : <RoutingTab />}
    </Flex>
  );
}
