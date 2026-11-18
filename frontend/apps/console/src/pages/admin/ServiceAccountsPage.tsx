import { App, Button, Checkbox, Flex, Form, Input, Switch, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  serviceAccountKeys,
  useCreateServiceAccount,
  useServiceAccountRoles,
  useServiceAccounts,
  useSetServiceAccountRole,
  useUpdateServiceAccount,
  type ServiceAccount,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useListChannel } from '@supportx/realtime';
import {
  Drawer,
  FilterBar,
  FormProblem,
  ListPage,
  NoAccess,
  PageHeader,
  ToneTag,
  WriteButton,
  lengthLimit,
  reportError,
  useAccess,
  useFormProblem,
  useLabel,
} from '@supportx/ui';
import { useQueryClient } from '@tanstack/react-query';

import { UserPicker } from '../incidents/pickers';

const NAME_MAX = 100;
const DESCRIPTION_MAX = 500;

/**
 * Admin > Service accounts (WP-057 S4a, REQ-SEC-036, template C): non-person identities API
 * clients act as. Each has an owner who answers for it; when the owner leaves it is flagged
 * until someone takes it over. Connector and workflow identities are listed, managed on their
 * own screens.
 */
export function ServiceAccountsPage() {
  const t = useLabel();
  const { can } = useAccess();
  const list = useListFormat();
  const allowed = can('api_keys.manage');
  const accounts = useServiceAccounts(allowed);
  const queryClient = useQueryClient();
  // A service identity is a user: the users list's channel carries its changes.
  useListChannel(allowed ? 'users' : null, () => {
    void queryClient.invalidateQueries({ queryKey: serviceAccountKeys.all });
  });
  const [open, setOpen] = useState<ServiceAccount | 'new'>();
  if (!allowed) return <NoAccess titleKey="nav.admin_service_accounts" />;
  const rows = accounts.data ?? [];
  return (
    <ListPage
      testId="service-accounts"
      header={
        <PageHeader
          title={t('service_accounts.title')}
          extra={
            <WriteButton
              type="primary"
              onClick={() => {
                setOpen('new');
              }}
              data-testid="service-account-new"
            >
              {t('service_accounts.new')}
            </WriteButton>
          }
        />
      }
      filters={<FilterBar testId="service-accounts-filters" />}
    >
      <Typography.Paragraph type="secondary">{t('service_accounts.help')}</Typography.Paragraph>
      <div
        role="region"
        aria-label={t('service_accounts.title')}
        tabIndex={0}
        style={{ overflowX: 'auto' }}
      >
        <Table<ServiceAccount>
          rowKey="id"
          data-testid="service-accounts-table"
          loading={accounts.isPending}
          dataSource={rows}
          pagination={false}
          locale={{ emptyText: t('service_accounts.empty') }}
          columns={[
            {
              key: 'name',
              title: t('service_accounts.col.name'),
              render: (_, row) => (
                <Flex vertical gap={2}>
                  <Button
                    type="link"
                    style={{ padding: 0, height: 'auto', textAlign: 'start' }}
                    onClick={() => {
                      setOpen(row);
                    }}
                    data-testid={`service-account-${row.id}`}
                  >
                    <bdi>{row.name}</bdi>
                  </Button>
                  {row.description !== null && (
                    <Typography.Text type="secondary">
                      <bdi>{row.description}</bdi>
                    </Typography.Text>
                  )}
                </Flex>
              ),
            },
            {
              key: 'owner',
              title: t('service_accounts.col.owner'),
              render: (_, row) =>
                !row.managed_here ? (
                  <Typography.Text type="secondary">
                    {t('service_accounts.managed_elsewhere')}
                  </Typography.Text>
                ) : (
                  <Flex gap={4} wrap align="center">
                    <bdi>{row.owner_name ?? ''}</bdi>
                    {row.needs_new_owner && (
                      <ToneTag tone="warning" testId={`service-account-handover-${row.id}`}>
                        {t('service_accounts.needs_new_owner')}
                      </ToneTag>
                    )}
                  </Flex>
                ),
            },
            {
              key: 'roles',
              title: t('service_accounts.col.roles'),
              render: (_, row) => list(row.roles.map((r) => r.name)),
            },
            {
              key: 'keys',
              title: t('service_accounts.col.keys'),
              width: 1,
              render: (_, row) => row.keys,
            },
            {
              key: 'state',
              title: t('service_accounts.col.state'),
              width: 1,
              render: (_, row) => (
                <ToneTag tone={row.active ? 'success' : 'info'}>
                  {t(row.active ? 'service_accounts.active' : 'service_accounts.inactive')}
                </ToneTag>
              ),
            },
          ]}
        />
      </div>
      {open !== undefined && (
        <AccountDrawer
          account={open === 'new' ? undefined : open}
          onClose={() => {
            setOpen(undefined);
          }}
        />
      )}
    </ListPage>
  );
}

function AccountDrawer({ account, onClose }: { account?: ServiceAccount; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  const create = useCreateServiceAccount();
  const update = useUpdateServiceAccount();
  const problem = useFormProblem();
  const [key] = useState(() => crypto.randomUUID());
  const [name, setName] = useState(account?.name ?? '');
  const [description, setDescription] = useState(account?.description ?? '');
  const [owner, setOwner] = useState<string | null>(account?.owner_id ?? null);
  const readOnly = account !== undefined && !account.managed_here;
  const pending = create.isPending || update.isPending;
  const save = () => {
    problem.clear();
    const done = {
      onSuccess: () => {
        void message.success(t('service_accounts.saved'));
        onClose();
      },
      onError: (error: unknown) => problem.show(error),
    };
    if (account === undefined) {
      if (owner === null) return;
      create.mutate(
        {
          body: { name: name.trim(), description: description.trim() || null, owner_id: owner },
          key,
        },
        done,
      );
      return;
    }
    update.mutate(
      {
        id: account.id,
        version: account.version,
        body: {
          ...(name.trim() !== account.name ? { name: name.trim() } : {}),
          ...((description.trim() || null) !== account.description
            ? { description: description.trim() || null }
            : {}),
          ...(owner !== null && owner !== account.owner_id ? { owner_id: owner } : {}),
        },
      },
      done,
    );
  };
  return (
    <Drawer
      open
      onClose={onClose}
      width={560}
      title={account === undefined ? t('service_accounts.new') : account.name}
      destroyOnHidden
      data-testid="service-account-drawer"
      footer={
        readOnly ? undefined : (
          <Flex justify="end" gap={8}>
            <Button onClick={onClose}>{t('actions.cancel')}</Button>
            <WriteButton
              type="primary"
              loading={pending}
              disabled={name.trim() === '' || owner === null}
              onClick={save}
              data-testid="service-account-save"
            >
              {t('actions.save')}
            </WriteButton>
          </Flex>
        )
      }
    >
      {readOnly ? (
        <Typography.Paragraph>{t('service_accounts.managed_elsewhere_help')}</Typography.Paragraph>
      ) : (
        <Form layout="vertical">
          <Form.Item label={t('service_accounts.col.name')} htmlFor="sa-name" required>
            <Input
              id="sa-name"
              value={name}
              count={lengthLimit(NAME_MAX)}
              onChange={(event) => {
                setName(event.target.value);
              }}
              data-testid="service-account-name"
            />
          </Form.Item>
          <Form.Item label={t('service_accounts.description')} htmlFor="sa-description">
            <Input.TextArea
              id="sa-description"
              value={description}
              count={lengthLimit(DESCRIPTION_MAX)}
              autoSize={{ minRows: 2, maxRows: 5 }}
              onChange={(event) => {
                setDescription(event.target.value);
              }}
              data-testid="service-account-description"
            />
          </Form.Item>
          <Form.Item
            label={t('service_accounts.col.owner')}
            htmlFor="sa-owner"
            help={t('service_accounts.owner_help')}
            required
          >
            <UserPicker
              id="sa-owner"
              value={owner}
              onChange={setOwner}
              testId="service-account-owner"
              ariaLabel={t('service_accounts.col.owner')}
            />
          </Form.Item>
          <FormProblem problem={problem} />
        </Form>
      )}
      {account !== undefined && account.managed_here && (
        <>
          <ActiveSwitch account={account} />
          <RolesSection account={account} />
        </>
      )}
    </Drawer>
  );
}

/** On or off: its keys stop or start at once (a recent sign-in, the server asks). */
function ActiveSwitch({ account }: { account: ServiceAccount }) {
  const t = useLabel();
  const update = useUpdateServiceAccount();
  return (
    <Flex gap={8} align="center" style={{ marginBlock: 16 }}>
      <Switch
        checked={account.active}
        loading={update.isPending}
        aria-labelledby="sa-active-label"
        onChange={(active) => {
          update.mutate(
            { id: account.id, version: account.version, body: { active } },
            { onError: reportError },
          );
        }}
        data-testid="service-account-active"
      />
      <Typography.Text id="sa-active-label">{t('service_accounts.active_switch')}</Typography.Text>
    </Flex>
  );
}

/** Its roles: only those a service account may hold, and never more than your own rights. */
function RolesSection({ account }: { account: ServiceAccount }) {
  const t = useLabel();
  const roles = useServiceAccountRoles(account.id);
  const set = useSetServiceAccountRole();
  const held = new Set((roles.data?.roles ?? []).map((r) => r.id));
  return (
    <Flex vertical gap={8} data-testid="service-account-roles">
      <Typography.Title level={5} style={{ margin: 0 }}>
        {t('service_accounts.col.roles')}
      </Typography.Title>
      {(roles.data?.offered ?? []).map((role) => (
        <Checkbox
          key={role.id}
          checked={held.has(role.id)}
          disabled={set.isPending}
          onChange={(event) => {
            set.mutate(
              { id: account.id, roleId: role.id, held: event.target.checked },
              { onError: reportError },
            );
          }}
          data-testid={`service-account-role-${role.key}`}
        >
          <bdi>{role.name}</bdi>
        </Checkbox>
      ))}
    </Flex>
  );
}
