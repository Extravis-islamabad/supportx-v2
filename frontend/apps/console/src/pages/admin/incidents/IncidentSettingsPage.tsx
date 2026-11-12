import { Alert, Flex, Skeleton } from 'antd';
import { Navigate, useNavigate, useParams } from 'react-router';

import { useIncidentCatalogue, type PickList } from '@supportx/api-client';
import {
  featureState,
  NoAccess,
  PageHeader,
  SectionNav,
  useAccess,
  useLabel,
  useLicence,
} from '@supportx/ui';

import { CategoriesTab } from './CategoriesTab';
import { ClosingTab } from './ClosingTab';
import { CustomFieldsTab } from './CustomFieldsTab';
import { GeneralTab } from './GeneralTab';
import { PickListEditor } from './PickListEditor';
import { PriorityTab } from './PriorityTab';
import { ReplyTemplatesTab } from './ReplyTemplatesTab';
import { TaskTemplatesTab } from './TaskTemplatesTab';
import { StatusesTab } from './StatusesTab';
import { TemplatesTab } from './TemplatesTab';
import { RepeatRulesTab } from './RepeatRulesTab';

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
  'closing',
  'reply-templates',
  'task-templates',
  'repeat-rules',
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
  const licence = useLicence();
  const repeats = featureState('problem', {
    has: licence.has,
    managesLicence: licence.isAdmin,
  });
  const navigate = useNavigate();
  const { section } = useParams();
  // The service desk's configure right (WP-042), or settings.manage for every area.
  const allowed = can('config.service_desk') || can('settings.manage');
  const catalogue = useIncidentCatalogue(allowed);
  if (!allowed) return <NoAccess titleKey="nav.admin_incidents" />;
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
      case 'task-templates':
        return <TaskTemplatesTab />;
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
      case 'closing':
        return <ClosingTab catalogue={cat} />;
      case 'repeat-rules':
        // While the plan loads, `has` says yes to everything: wait for it, so the rules are never
        // asked for on a plan without problems (lane B's flake report, #375's CI).
        return licence.entitlements === null ? (
          <Skeleton active />
        ) : (
          <RepeatRulesTab entitled={repeats === 'on'} />
        );
      default:
        return null;
    }
  })();
  return (
    // minWidth 0: the tab bar fits the screen and folds the rest into "more" (QA BUG-03).
    <Flex vertical gap={8} style={{ minWidth: 0 }}>
      <PageHeader level={2} title={t('settings.incidents_title')} />
      <SectionNav
        label={t('settings.incidents_title')}
        active={current}
        onNavigate={(path) => void navigate(path)}
        // Repeated incidents are the problem module's: the nav's rule for features outside the
        // plan (on, locked with the hint, or hidden; D-044's switch reaches it there).
        items={SECTIONS.filter((key) => key !== 'repeat-rules' || repeats !== 'hidden').map(
          (key) => ({
            key,
            label: t(`settings.section.${key}`),
            path: `/admin/incidents/${key}`,
          }),
        )}
        testId="settings-sections"
      />
      {body}
    </Flex>
  );
}
