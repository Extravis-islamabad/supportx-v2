import { useQueryClient } from '@tanstack/react-query';
import { App, Card, Flex, Form, Select, Skeleton, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  serviceRequestKeys,
  useServiceRequestCatalogue,
  useServiceRequestSettingsChange,
  type OnBehalfScope,
} from '@supportx/api-client';
import { PageHeader, reportError, useLabel, WriteButton } from '@supportx/ui';

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
    version: number;
  }>();
  if (catalogue.isLoading || catalogue.data === undefined) return <Skeleton active />;
  const saved = catalogue.data;
  const scope = draft?.scope ?? saved.on_behalf_scope;
  const hidden = draft?.hidden ?? saved.approvals_hidden_from_requesters;
  const signIn = draft?.signIn ?? saved.approvals_require_sign_in;
  const dirty =
    draft !== undefined &&
    (draft.scope !== saved.on_behalf_scope ||
      draft.hidden !== saved.approvals_hidden_from_requesters ||
      draft.signIn !== saved.approvals_require_sign_in);
  const edit = (next: Partial<{ scope: OnBehalfScope; hidden: boolean; signIn: boolean }>) => {
    setDraft({ scope, hidden, signIn, version: draft?.version ?? saved.version, ...next });
  };
  return (
    <Flex vertical gap={16} style={{ maxWidth: 760 }}>
      <PageHeader title={t('nav.admin_requests')} />
      <Card title={t('requests.settings.raising_for_others')}>
        <Form
          layout="vertical"
          onFinish={() => {
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
          }}
        >
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
          <WriteButton
            type="primary"
            htmlType="submit"
            disabled={!dirty}
            loading={change.isPending}
            data-testid="sr-settings-save"
          >
            {t('actions.save')}
          </WriteButton>
        </Form>
      </Card>
    </Flex>
  );
}
