import { Alert, Flex, Skeleton, Tabs, Typography } from 'antd';
import { Navigate, useNavigate, useParams } from 'react-router';

import { useIncidentCatalogue, type PickList } from '@supportx/api-client';
import { NoAccess, useAccess, useLabel } from '@supportx/ui';

import { CategoriesTab } from './CategoriesTab';
import { CustomFieldsTab } from './CustomFieldsTab';
import { GeneralTab } from './GeneralTab';
import { PickListEditor } from './PickListEditor';
import { PriorityTab } from './PriorityTab';
import { ReplyTemplatesTab } from './ReplyTemplatesTab';
import { StatusesTab } from './StatusesTab';
import { TemplatesTab } from './TemplatesTab';

const SECTIONS = [
  'general',
  'templates',
  'custom-fields',
  'statuses',
  'reasons',
  'priority',
  'categories',
  'levels',
  'closure-codes',
  'reply-templates',
] as const;
type Section = (typeof SECTIONS)[number];
const REASON_LISTS: PickList[] = ['pause', 'third_party', 'cancel', 'reopen', 'reassign'];

/**
 * Admin › Incidents (WP-020c, D-056): one home for everything that shapes incidents. Every
 * change is audited and reaches open forms and lists live. Values, not structure: statuses
 * and transitions keep their shape until the life-cycle designer.
 */
export function IncidentSettingsPage() {
  const t = useLabel();
  const { can } = useAccess();
  const navigate = useNavigate();
  const { section } = useParams();
  const catalogue = useIncidentCatalogue(can('settings.manage'));
  if (!can('settings.manage')) return <NoAccess titleKey="nav.admin_incidents" />;
  if (section === undefined || !(SECTIONS as readonly string[]).includes(section)) {
    return <Navigate to="/admin/incidents/general" replace />;
  }
  const current = section as Section;
  const body = (() => {
    if (catalogue.isError) {
      return (
        <Alert
          type="error"
          showIcon
          message={t('settings.load_failed')}
          data-testid="settings-error"
        />
      );
    }
    // Sections with their own data do not wait for the catalogue (no request waterfall: the
    // custom fields list loads at once, also under load; lane B's flaky-test report).
    switch (current) {
      case 'templates':
        return <TemplatesTab />;
      case 'custom-fields':
        return <CustomFieldsTab />;
      case 'categories':
        return <CategoriesTab />;
      case 'reply-templates':
        return <ReplyTemplatesTab />;
      default:
        break;
    }
    if (catalogue.data === undefined) return <Skeleton active />;
    const cat = catalogue.data;
    switch (current) {
      case 'general':
        return <GeneralTab catalogue={cat} />;
      case 'statuses':
        return <StatusesTab catalogue={cat} />;
      case 'reasons':
        return (
          <Flex vertical gap={16}>
            {REASON_LISTS.map((list) => (
              <PickListEditor
                key={list}
                list={list}
                title={t(`pick_list.${list}`)}
                description={t(`settings.reason_list_help.${list}`)}
                values={cat.reasons.filter((r) => r.list === list)}
              />
            ))}
          </Flex>
        );
      case 'priority':
        return <PriorityTab catalogue={cat} />;
      case 'levels':
        return (
          <PickListEditor
            list="level"
            title={t('pick_list.level')}
            description={t('settings.levels_help')}
            values={cat.levels}
            withColour
          />
        );
      case 'closure-codes':
        return (
          <PickListEditor
            list="closure_code"
            title={t('pick_list.closure_code')}
            description={t('settings.closure_codes_help')}
            values={cat.closure_codes}
          />
        );
      default:
        return null;
    }
  })();
  return (
    // minWidth 0: the tab bar fits the screen and folds the rest into "more" (QA BUG-03).
    <Flex vertical gap={8} style={{ minWidth: 0 }}>
      <Typography.Title level={2}>{t('settings.incidents_title')}</Typography.Title>
      <Tabs
        activeKey={current}
        onChange={(key) => void navigate(`/admin/incidents/${key}`)}
        items={SECTIONS.map((key) => ({ key, label: t(`settings.section.${key}`) }))}
        data-testid="settings-sections"
      />
      {body}
    </Flex>
  );
}
