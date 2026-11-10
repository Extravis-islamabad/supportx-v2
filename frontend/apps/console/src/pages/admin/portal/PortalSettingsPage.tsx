import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons';
import { Button, Checkbox, Flex, List, Select, Skeleton, Switch, Tag, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, type ReactNode } from 'react';

import {
  useCatalogSettings,
  useCatalogSettingsChange,
  useIncidentCatalogue,
  useIncidentSettingsChange,
  usePortalSettings,
  usePortalSettingsChange,
  portalSettingsKey,
  useServiceRequestCatalogue,
  useServiceRequestSettingsChange,
  type OnBehalfScope,
  type PortalSearchSource,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  PageHeader,
  reportError,
  SettingsCard,
  StickySaveBar,
  useLabel,
  useLicence,
  useSettingsDraft,
} from '@supportx/ui';

const SOURCES: PortalSearchSource[] = ['items', 'articles', 'announcements', 'requests'];
const SCOPES: OnBehalfScope[] = ['same_department', 'same_site', 'all_requesters', 'all_users'];
// Settings that come with their own work packages: shown, explained, not yet switchable.
const LATER = ['show_cost', 'own_assets', 'public_pages', 'guest_requests', 'self_registration'];

/** One setting: its name, a one-line explanation, and its control (REQ-PRT-031). */
function Setting({
  name,
  hint,
  children,
  testId,
}: {
  name: string;
  hint: string;
  children: ReactNode;
  testId: string;
}) {
  return (
    <Flex justify="space-between" align="center" gap={16} data-testid={testId} wrap>
      <Flex vertical gap={2} style={{ minWidth: 0, flex: 1 }}>
        <Typography.Text strong>{name}</Typography.Text>
        <Typography.Text type="secondary">{hint}</Typography.Text>
      </Flex>
      {children}
    </Flex>
  );
}

/**
 * Every portal setting on one page (WP-032 D8, D-143, REQ-PRT-031), in groups, each with a one
 * line explanation. Each is saved where it lives (the type settings, the catalog's, the
 * portal's own row) with If-Match and that owner's audit entry; a change reaches open portals at
 * once. The admin search finds each by its name (setup map). Later ones are shown as later.
 */
export function PortalSettingsPage() {
  const t = useLabel();
  const { writable } = useLicence(); // read-only licence: nothing here saves (coverage §17)
  const queryClient = useQueryClient();
  // Another admin's change shows here at once (§8).
  useTenantChannel((event) => {
    if (event.type === 'work_items.portal_settings_changed') {
      void queryClient.invalidateQueries({ queryKey: portalSettingsKey });
    }
  });
  const portal = usePortalSettings();
  const portalChange = usePortalSettingsChange();
  const requests = useServiceRequestCatalogue();
  const requestChange = useServiceRequestSettingsChange();
  const incidents = useIncidentCatalogue();
  const incidentChange = useIncidentSettingsChange();
  const catalog = useCatalogSettings();
  const catalogChange = useCatalogSettingsChange();
  const ready =
    portal.data !== undefined &&
    requests.data !== undefined &&
    incidents.data !== undefined &&
    catalog.data !== undefined;
  // One draft for the page (template E, D-147): switches change it, the bar saves it.
  const saved = useMemo(
    () => ({
      hideDefault: catalog.data?.hide_default_incident_template ?? false,
      incidentDue: incidents.data?.portal_show_due_time ?? false,
      requestDue: requests.data?.portal_show_due_time ?? false,
      onBehalf: requests.data?.on_behalf_scope ?? 'same_department',
      approvalsHidden: requests.data?.approvals_hidden_from_requesters ?? false,
      approvalsSignIn: requests.data?.approvals_require_sign_in ?? false,
      sources: portal.data?.search_sources ?? [],
      profileEditing: portal.data?.profile_editing ?? false,
      reminders: portal.data?.requester_reminders ?? false,
    }),
    [portal.data, requests.data, catalog.data, incidents.data],
  );
  const { draft, set, changes, changed, discard } = useSettingsDraft(saved);
  const saving =
    portalChange.isPending ||
    requestChange.isPending ||
    incidentChange.isPending ||
    catalogChange.isPending;
  if (!ready) return <Skeleton active />;
  const p = portal.data;
  const sr = requests.data;
  const cat = catalog.data;
  // Each setting is saved where it lives, only what changed, with that owner's If-Match.
  const save = async () => {
    try {
      if (changed.hideDefault !== undefined) {
        await catalogChange.mutateAsync({
          body: { hide_default_incident_template: changed.hideDefault },
          version: cat.version,
        });
      }
      if (changed.incidentDue !== undefined) {
        await incidentChange.mutateAsync({
          change: { kind: 'settings', body: { portal_show_due_time: changed.incidentDue } },
        });
      }
      const forRequests = {
        ...(changed.requestDue === undefined ? {} : { portal_show_due_time: changed.requestDue }),
        ...(changed.onBehalf === undefined ? {} : { on_behalf_scope: changed.onBehalf }),
        ...(changed.approvalsHidden === undefined
          ? {}
          : { approvals_hidden_from_requesters: changed.approvalsHidden }),
        ...(changed.approvalsSignIn === undefined
          ? {}
          : { approvals_require_sign_in: changed.approvalsSignIn }),
      };
      if (Object.keys(forRequests).length > 0) {
        await requestChange.mutateAsync({ body: forRequests, version: sr.version });
      }
      const forPortal = {
        ...(changed.sources === undefined ? {} : { search_sources: changed.sources }),
        ...(changed.profileEditing === undefined
          ? {}
          : { profile_editing: changed.profileEditing }),
        ...(changed.reminders === undefined ? {} : { requester_reminders: changed.reminders }),
      };
      if (Object.keys(forPortal).length > 0) {
        await portalChange.mutateAsync({ body: forPortal, version: p.version });
      }
    } catch (error) {
      reportError(error);
    }
  };
  const sources = draft.sources;
  const move = (source: PortalSearchSource, by: number) => {
    const at = sources.indexOf(source);
    const next = [...sources];
    next.splice(at, 1);
    next.splice(at + by, 0, source);
    set({ sources: next });
  };
  const toggle = (source: PortalSearchSource, on: boolean) => {
    const next = on ? [...sources, source] : sources.filter((s) => s !== source);
    if (next.length > 0) set({ sources: next });
  };

  return (
    <Flex vertical gap={16} style={{ maxWidth: 860 }} data-testid="portal-settings">
      <PageHeader title={t('nav.admin_portal')} description={t('portal_settings.intro')} />
      <SettingsCard title={t('portal_settings.group.requests')}>
        <Flex vertical gap={16}>
          <Setting
            name={t('portal_settings.hide_default_form')}
            hint={t('portal_settings.hide_default_form_hint')}
            testId="ps-hide-default-form"
          >
            <Switch
              disabled={!writable}
              aria-label={t('portal_settings.hide_default_form')}
              checked={draft.hideDefault}
              onChange={(on) => {
                set({ hideDefault: on });
              }}
            />
          </Setting>
          <Setting
            name={t('portal_settings.due_incidents')}
            hint={t('portal_settings.due_incidents_hint')}
            testId="ps-due-incidents"
          >
            <Switch
              disabled={!writable}
              aria-label={t('portal_settings.due_incidents')}
              checked={draft.incidentDue}
              onChange={(on) => {
                set({ incidentDue: on });
              }}
            />
          </Setting>
          <Setting
            name={t('portal_settings.due_requests')}
            hint={t('portal_settings.due_requests_hint')}
            testId="ps-due-requests"
          >
            <Switch
              disabled={!writable}
              aria-label={t('portal_settings.due_requests')}
              checked={draft.requestDue}
              onChange={(on) => {
                set({ requestDue: on });
              }}
            />
          </Setting>
        </Flex>
      </SettingsCard>
      <SettingsCard title={t('portal_settings.group.people')}>
        <Setting
          name={t('portal_settings.on_behalf')}
          hint={t('portal_settings.on_behalf_hint')}
          testId="ps-on-behalf"
        >
          <Select
            disabled={!writable}
            aria-label={t('portal_settings.on_behalf')}
            style={{ minWidth: 240 }}
            value={draft.onBehalf}
            onChange={(scope: OnBehalfScope) => {
              set({ onBehalf: scope });
            }}
            options={SCOPES.map((s) => ({ value: s, label: t(`work_item_on_behalf_scope.${s}`) }))}
          />
        </Setting>
      </SettingsCard>
      <SettingsCard title={t('portal_settings.group.approvals')}>
        <Flex vertical gap={16}>
          <Setting
            name={t('portal_settings.approvals_hidden')}
            hint={t('portal_settings.approvals_hidden_hint')}
            testId="ps-approvals-hidden"
          >
            <Switch
              disabled={!writable}
              aria-label={t('portal_settings.approvals_hidden')}
              checked={draft.approvalsHidden}
              onChange={(on) => {
                set({ approvalsHidden: on });
              }}
            />
          </Setting>
          <Setting
            name={t('portal_settings.approvals_sign_in')}
            hint={t('portal_settings.approvals_sign_in_hint')}
            testId="ps-approvals-sign-in"
          >
            <Switch
              disabled={!writable}
              aria-label={t('portal_settings.approvals_sign_in')}
              checked={draft.approvalsSignIn}
              onChange={(on) => {
                set({ approvalsSignIn: on });
              }}
            />
          </Setting>
        </Flex>
      </SettingsCard>
      <SettingsCard title={t('portal_settings.group.portal')}>
        <Flex vertical gap={16}>
          <Flex vertical gap={8} data-testid="ps-search-sources">
            <Typography.Text strong>{t('portal_settings.search_sources')}</Typography.Text>
            <Typography.Text type="secondary">
              {t('portal_settings.search_sources_hint')}
            </Typography.Text>
            <List
              size="small"
              bordered
              dataSource={[...sources, ...SOURCES.filter((s) => !sources.includes(s))]}
              renderItem={(source) => {
                const on = sources.includes(source);
                const at = sources.indexOf(source);
                return (
                  <List.Item
                    key={source}
                    actions={
                      on
                        ? [
                            <Button
                              key="up"
                              size="small"
                              type="text"
                              icon={<ArrowUpOutlined />}
                              disabled={at === 0}
                              aria-label={t('portal_settings.move_up', {
                                name: t(`portal.search.group.${source}`),
                              })}
                              onClick={() => {
                                move(source, -1);
                              }}
                            />,
                            <Button
                              key="down"
                              size="small"
                              type="text"
                              icon={<ArrowDownOutlined />}
                              disabled={at === sources.length - 1}
                              aria-label={t('portal_settings.move_down', {
                                name: t(`portal.search.group.${source}`),
                              })}
                              onClick={() => {
                                move(source, 1);
                              }}
                            />,
                          ]
                        : []
                    }
                  >
                    <Checkbox
                      disabled={!writable || (on && sources.length === 1)}
                      checked={on}
                      onChange={(e) => {
                        toggle(source, e.target.checked);
                      }}
                      data-testid={`ps-source-${source}`}
                    >
                      {t(`portal.search.group.${source}`)}
                    </Checkbox>
                  </List.Item>
                );
              }}
            />
          </Flex>
          <Setting
            name={t('portal_settings.profile_editing')}
            hint={t('portal_settings.profile_editing_hint')}
            testId="ps-profile-editing"
          >
            <Switch
              disabled={!writable}
              aria-label={t('portal_settings.profile_editing')}
              checked={draft.profileEditing}
              onChange={(on) => {
                set({ profileEditing: on });
              }}
            />
          </Setting>
          <Setting
            name={t('portal_settings.reminders')}
            hint={t('portal_settings.reminders_hint')}
            testId="ps-reminders"
          >
            <Switch
              disabled={!writable}
              aria-label={t('portal_settings.reminders')}
              checked={draft.reminders}
              onChange={(on) => {
                set({ reminders: on });
              }}
            />
          </Setting>
        </Flex>
      </SettingsCard>
      <SettingsCard title={t('portal_settings.group.later')}>
        <Flex vertical gap={12}>
          {LATER.map((key) => (
            <Setting
              key={key}
              name={t(`portal_settings.later.${key}`)}
              hint={t('portal_settings.later_hint')}
              testId={`ps-later-${key}`}
            >
              <Tag>{t('portal_settings.later_tag')}</Tag>
            </Setting>
          ))}
        </Flex>
      </SettingsCard>
      {writable && (
        <StickySaveBar
          changes={changes}
          saving={saving}
          onDiscard={discard}
          onSave={() => void save()}
          testId="portal-settings-save-bar"
        />
      )}
    </Flex>
  );
}
