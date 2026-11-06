import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Checkbox,
  Flex,
  List,
  Select,
  Skeleton,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';

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
import { PageHeader, reportError, useLabel } from '@supportx/ui';

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
  if (
    portal.data === undefined ||
    requests.data === undefined ||
    incidents.data === undefined ||
    catalog.data === undefined
  ) {
    return <Skeleton active />;
  }
  const p = portal.data;
  const sr = requests.data;
  const inc = incidents.data;
  const cat = catalog.data;
  const onError = { onError: reportError };
  const savePortal = (body: Parameters<typeof portalChange.mutate>[0]['body']) => {
    portalChange.mutate({ body, version: p.version }, onError);
  };
  const saveRequests = (body: Parameters<typeof requestChange.mutate>[0]['body']) => {
    requestChange.mutate({ body, version: sr.version }, onError);
  };
  const sources = p.search_sources;
  const move = (source: PortalSearchSource, by: number) => {
    const at = sources.indexOf(source);
    const next = [...sources];
    next.splice(at, 1);
    next.splice(at + by, 0, source);
    savePortal({ search_sources: next });
  };
  const toggle = (source: PortalSearchSource, on: boolean) => {
    const next = on ? [...sources, source] : sources.filter((s) => s !== source);
    if (next.length > 0) savePortal({ search_sources: next });
  };

  return (
    <Flex vertical gap={16} style={{ maxWidth: 860 }} data-testid="portal-settings">
      <PageHeader title={t('nav.admin_portal')} description={t('portal_settings.intro')} />
      <Card title={t('portal_settings.group.requests')}>
        <Flex vertical gap={16}>
          <Setting
            name={t('portal_settings.hide_default_form')}
            hint={t('portal_settings.hide_default_form_hint')}
            testId="ps-hide-default-form"
          >
            <Switch
              aria-label={t('portal_settings.hide_default_form')}
              checked={cat.hide_default_incident_template}
              loading={catalogChange.isPending}
              onChange={(on) => {
                catalogChange.mutate(
                  { body: { hide_default_incident_template: on }, version: cat.version },
                  onError,
                );
              }}
            />
          </Setting>
          <Setting
            name={t('portal_settings.due_incidents')}
            hint={t('portal_settings.due_incidents_hint')}
            testId="ps-due-incidents"
          >
            <Switch
              aria-label={t('portal_settings.due_incidents')}
              checked={inc.portal_show_due_time}
              loading={incidentChange.isPending}
              onChange={(on) => {
                incidentChange.mutate(
                  { change: { kind: 'settings', body: { portal_show_due_time: on } } },
                  onError,
                );
              }}
            />
          </Setting>
          <Setting
            name={t('portal_settings.due_requests')}
            hint={t('portal_settings.due_requests_hint')}
            testId="ps-due-requests"
          >
            <Switch
              aria-label={t('portal_settings.due_requests')}
              checked={sr.portal_show_due_time}
              loading={requestChange.isPending}
              onChange={(on) => {
                saveRequests({ portal_show_due_time: on });
              }}
            />
          </Setting>
        </Flex>
      </Card>
      <Card title={t('portal_settings.group.people')}>
        <Setting
          name={t('portal_settings.on_behalf')}
          hint={t('portal_settings.on_behalf_hint')}
          testId="ps-on-behalf"
        >
          <Select
            aria-label={t('portal_settings.on_behalf')}
            style={{ minWidth: 240 }}
            value={sr.on_behalf_scope}
            onChange={(scope: OnBehalfScope) => {
              saveRequests({ on_behalf_scope: scope });
            }}
            options={SCOPES.map((s) => ({ value: s, label: t(`work_item_on_behalf_scope.${s}`) }))}
          />
        </Setting>
      </Card>
      <Card title={t('portal_settings.group.approvals')}>
        <Flex vertical gap={16}>
          <Setting
            name={t('portal_settings.approvals_hidden')}
            hint={t('portal_settings.approvals_hidden_hint')}
            testId="ps-approvals-hidden"
          >
            <Switch
              aria-label={t('portal_settings.approvals_hidden')}
              checked={sr.approvals_hidden_from_requesters}
              onChange={(on) => {
                saveRequests({ approvals_hidden_from_requesters: on });
              }}
            />
          </Setting>
          <Setting
            name={t('portal_settings.approvals_sign_in')}
            hint={t('portal_settings.approvals_sign_in_hint')}
            testId="ps-approvals-sign-in"
          >
            <Switch
              aria-label={t('portal_settings.approvals_sign_in')}
              checked={sr.approvals_require_sign_in}
              onChange={(on) => {
                saveRequests({ approvals_require_sign_in: on });
              }}
            />
          </Setting>
        </Flex>
      </Card>
      <Card title={t('portal_settings.group.portal')}>
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
                      checked={on}
                      disabled={on && sources.length === 1}
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
              aria-label={t('portal_settings.profile_editing')}
              checked={p.profile_editing}
              onChange={(on) => {
                savePortal({ profile_editing: on });
              }}
            />
          </Setting>
          <Setting
            name={t('portal_settings.reminders')}
            hint={t('portal_settings.reminders_hint')}
            testId="ps-reminders"
          >
            <Switch
              aria-label={t('portal_settings.reminders')}
              checked={p.requester_reminders}
              onChange={(on) => {
                savePortal({ requester_reminders: on });
              }}
            />
          </Setting>
        </Flex>
      </Card>
      <Card title={t('portal_settings.group.later')}>
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
      </Card>
    </Flex>
  );
}
