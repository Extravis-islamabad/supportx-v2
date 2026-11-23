import { useQueryClient } from '@tanstack/react-query';
import { App, Flex, Form, Select, Skeleton, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  serviceRequestKeys,
  useServiceRequestCatalogue,
  useServiceRequestSettingsChange,
  type OnBehalfScope,
} from '@supportx/api-client';
import { PageHeader, reportError, SettingsCard, StickySaveBar, useLabel } from '@supportx/ui';

import { LifecycleTab } from '../incidents/LifecycleTab';

// Whom a requester may raise a request for (REQ-SR-011), widest last. Staff raise for anyone;
// a requester always may raise for their own direct reports.
const SCOPES: OnBehalfScope[] = ['same_department', 'same_site', 'all_requesters', 'all_users'];

/**
 * Service request settings (WP-030): whom a requester may raise for, and whether requesters
 * see the approvals' names and comments (REQ-SR-024 AC3). The save sends If-Match on
 * the version the form started from; a change by someone else in between is refused (409), the
 * form reloads the saved settings and says so, never writing over their change.
 */
export function RequestSettingsPage() {
  const t = useLabel();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const catalogue = useServiceRequestCatalogue();
  const change = useServiceRequestSettingsChange();
  // The draft and the version it started from; undefined: the saved values show.
  const [draft, setDraft] = useState<{
    scope: OnBehalfScope;
    hidden: boolean;
    signIn: boolean;
    starts: boolean;
    version: number;
  }>();
  if (catalogue.isLoading || catalogue.data === undefined) return <Skeleton active />;
  const saved = catalogue.data;
  const scope = draft?.scope ?? saved.on_behalf_scope;
  const hidden = draft?.hidden ?? saved.approvals_hidden_from_requesters;
  const signIn = draft?.signIn ?? saved.approvals_require_sign_in;
  const starts = draft?.starts ?? saved.first_task_starts_work;
  const edit = (
    next: Partial<{ scope: OnBehalfScope; hidden: boolean; signIn: boolean; starts: boolean }>,
  ) => {
    setDraft({ scope, hidden, signIn, starts, version: draft?.version ?? saved.version, ...next });
  };
  const changes =
    draft === undefined
      ? 0
      : [
          draft.scope !== saved.on_behalf_scope,
          draft.hidden !== saved.approvals_hidden_from_requesters,
          draft.signIn !== saved.approvals_require_sign_in,
          draft.starts !== saved.first_task_starts_work,
        ].filter(Boolean).length;
  const submit = () => {
    if (draft === undefined) return;
    change.mutate(
      {
        body: {
          ...(draft.scope !== saved.on_behalf_scope && { on_behalf_scope: draft.scope }),
          ...(draft.hidden !== saved.approvals_hidden_from_requesters && {
            approvals_hidden_from_requesters: draft.hidden,
          }),
          ...(draft.signIn !== saved.approvals_require_sign_in && {
            approvals_require_sign_in: draft.signIn,
          }),
          ...(draft.starts !== saved.first_task_starts_work && {
            first_task_starts_work: draft.starts,
          }),
        },
        version: draft.version,
      },
      {
        onSuccess: () => {
          setDraft(undefined);
          void message.success(t('settings.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) {
            setDraft(undefined);
            void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.settings });
          }
          reportError(error);
        },
      },
    );
  };
  return (
    <Flex vertical gap={16} style={{ maxWidth: 760 }}>
      <PageHeader title={t('nav.admin_requests')} />
      <SettingsCard title={t('requests.settings.raising_for_others')}>
        <Form layout="vertical" component="div">
          <Form.Item
            label={t('requests.settings.on_behalf_scope')}
            htmlFor="sr-on-behalf-scope"
            extra={
              <Typography.Text type="secondary">
                {t('requests.settings.on_behalf_help')}
              </Typography.Text>
            }
          >
            <Select
              id="sr-on-behalf-scope"
              data-testid="sr-on-behalf-scope"
              aria-label={t('requests.settings.on_behalf_scope')}
              value={scope}
              onChange={(value: OnBehalfScope) => {
                edit({ scope: value });
              }}
              options={SCOPES.map((code) => ({
                value: code,
                label: t(`work_item_on_behalf_scope.${code}`),
              }))}
              style={{ maxWidth: 360 }}
            />
          </Form.Item>
          <Form.Item
            label={t('requests.settings.hide_approvals')}
            htmlFor="sr-hide-approvals"
            extra={
              <Typography.Text type="secondary">
                {t('requests.settings.hide_approvals_help')}
              </Typography.Text>
            }
          >
            <Switch
              id="sr-hide-approvals"
              checked={hidden}
              onChange={(value) => {
                edit({ hidden: value });
              }}
              data-testid="sr-hide-approvals"
            />
          </Form.Item>
          <Form.Item
            label={t('requests.settings.require_sign_in')}
            htmlFor="sr-require-sign-in"
            extra={
              <Typography.Text type="secondary">
                {t('requests.settings.require_sign_in_help')}
              </Typography.Text>
            }
          >
            <Switch
              id="sr-require-sign-in"
              checked={signIn}
              onChange={(value) => {
                edit({ signIn: value });
              }}
              data-testid="sr-require-sign-in"
            />
          </Form.Item>
        </Form>
      </SettingsCard>
      <SettingsCard title={t('requests.settings.fulfilment')}>
        <Form layout="vertical" component="div">
          <Form.Item
            label={t('requests.settings.first_task_starts_work')}
            htmlFor="sr-first-task-starts"
            extra={
              <Typography.Text type="secondary">
                {t('requests.settings.first_task_starts_work_help')}
              </Typography.Text>
            }
          >
            <Switch
              id="sr-first-task-starts"
              checked={starts}
              onChange={(value) => {
                edit({ starts: value });
              }}
              data-testid="sr-first-task-starts"
            />
          </Form.Item>
        </Form>
      </SettingsCard>
      {/* One save bar for the page (template E, D-147). */}
      <StickySaveBar
        changes={changes}
        saving={change.isPending}
        onDiscard={() => {
          setDraft(undefined);
        }}
        onSave={submit}
        testId="sr-settings-save-bar"
      />
      <LifecycleTab catalogue={saved} base="service-requests" />
    </Flex>
  );
}
