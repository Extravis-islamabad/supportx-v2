import { Alert, Button, Flex, Skeleton, Switch, Typography } from 'antd';
import { Navigate, useNavigate, useParams } from 'react-router';

import type { IncidentCatalogue } from '@supportx/api-client';
import {
  ConflictDialog,
  NoAccess,
  SectionNav,
  SettingsCard,
  SettingsPageHeader,
  StickySaveBar,
  useAccess,
  useLabel,
} from '@supportx/ui';

import { ClosingTab } from '../incidents/ClosingTab';
import {
  SettingsBaseContext,
  useDraft,
  useSettingsCatalogue,
  useSettingsSave,
} from '../incidents/helpers';
import { PickListEditor } from '../incidents/PickListEditor';
import { Problems } from '../incidents/shared';

const SECTIONS = ['closure-codes', 'closing', 'stages'] as const;
type Section = (typeof SECTIONS)[number];

/**
 * Admin › Releases (WP-058b S4, template E): how releases close (their own closure codes,
 * REQ-REL-050), what closing needs and which open work warns or blocks (REQ-REL-052), and
 * whether a stage's open tasks hold its move (REQ-REL-048). The incident settings screens are
 * shared and write the release settings (SettingsBaseContext); the same gate as the API.
 */
export function ReleaseSettingsPage() {
  return (
    <SettingsBaseContext.Provider value="releases">
      <ReleaseSettings />
    </SettingsBaseContext.Provider>
  );
}

function ReleaseSettings() {
  const t = useLabel();
  const { can } = useAccess();
  const navigate = useNavigate();
  const { section } = useParams();
  const allowed = can('config.service_desk') || can('settings.manage');
  const catalogue = useSettingsCatalogue(allowed);
  if (!allowed) return <NoAccess titleKey="nav.admin_releases" />;
  if (section === undefined || !(SECTIONS as readonly string[]).includes(section)) {
    return <Navigate to="/admin/releases/closure-codes" replace />;
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
    if (catalogue.data === undefined) return <Skeleton active />;
    const cat = catalogue.data;
    switch (current) {
      case 'closure-codes':
        return (
          <PickListEditor
            list="closure_code"
            title={t('pick_list.closure_code')}
            description={t('settings.release_closure_codes_help')}
            values={cat.closure_codes}
          />
        );
      case 'closing':
        return <ClosingTab catalogue={cat} />;
      case 'stages':
        return <StagesTab catalogue={cat} />;
    }
  })();
  return (
    <Flex vertical gap={8} style={{ minWidth: 0 }}>
      <SettingsPageHeader
        title={t('nav.admin_releases')}
        description={t('setup.page.releases.description')}
        testId="admin-page-header"
      />
      <SectionNav
        label={t('nav.admin_releases')}
        active={current}
        onNavigate={(path) => void navigate(path)}
        items={SECTIONS.map((key) => ({
          key,
          label: t(`settings.section.${key}`),
          path: `/admin/releases/${key}`,
        }))}
        testId="settings-sections"
      />
      {body}
    </Flex>
  );
}

/** A stage's open tasks hold its move out, or only warn (REQ-REL-048; on by default). */
function StagesTab({ catalogue }: { catalogue: IncidentCatalogue }) {
  const t = useLabel();
  const { save, conflictDialog, pending, problems, clear } = useSettingsSave();
  const source = { block: catalogue.open_stage_tasks_block };
  const draftState = useDraft(source, catalogue.version);
  const { draft, edit, stale } = draftState;
  const changes = draft.block === source.block ? 0 : 1;
  const reset = () => {
    clear();
    draftState.reset();
  };
  return (
    <Flex vertical gap={16}>
      <SettingsCard title={t('settings.stages.title')} testId="settings-stages">
        {stale && (
          <Alert
            type="warning"
            showIcon
            role="status"
            style={{ marginBottom: 12 }}
            message={t('settings.stale')}
            action={
              <Button size="small" onClick={reset} data-testid="settings-stale-reload">
                {t('live.reload')}
              </Button>
            }
            data-testid="settings-stale"
          />
        )}
        <Flex gap={12} align="start">
          <Switch
            id="settings-open-stage-tasks-block"
            checked={draft.block}
            onChange={(checked) => {
              edit({ block: checked });
            }}
            data-testid="settings-open-stage-tasks-block"
          />
          <label htmlFor="settings-open-stage-tasks-block">
            <Typography.Text strong>{t('settings.stages.open_tasks_block')}</Typography.Text>
            <br />
            <Typography.Text type="secondary">
              {t('settings.stages.open_tasks_block_help')}
            </Typography.Text>
          </label>
        </Flex>
        <Problems problems={problems} />
      </SettingsCard>
      <StickySaveBar
        changes={changes}
        saving={pending}
        onDiscard={reset}
        onSave={() => {
          save(
            { kind: 'settings', body: { open_stage_tasks_block: draft.block } },
            reset,
            draftState.base,
          );
        }}
        testId="settings-stages-save-bar"
      />
      <ConflictDialog {...conflictDialog} />
    </Flex>
  );
}
