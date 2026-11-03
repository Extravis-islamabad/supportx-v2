import {
  Alert,
  App,
  Button,
  Drawer,
  Empty,
  Flex,
  Input,
  InputNumber,
  Radio,
  Select,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  ApiError,
  queryKeys,
  useCreateDirectory,
  useDirectories,
  useDirectoryGroups,
  useRemoveDirectory,
  useStructure,
  useSyncDirectoryNow,
  useUpdateDirectory,
  type Directory,
  type DirectoryInput,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  FormProblem,
  lengthLimit,
  markHandled,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

type Scope = DirectoryInput['scope'];
type CredentialKind = DirectoryInput['credential_kind'];
type EmailFrom = NonNullable<NonNullable<DirectoryInput['mapping']>['email_from']>;
interface Group {
  external_id: string;
  name: string;
}
interface Mapped extends Group {
  group_id: string;
}
const ATTRIBUTES = ['department', 'officeLocation', 'city', 'companyName', 'state', 'country'];

interface Form {
  name: string;
  directory_tenant: string;
  client_id: string;
  credential_kind: CredentialKind;
  credential: string;
  scope: Scope;
  scope_groups: Group[];
  group_mappings: Mapped[];
  email_from: EmailFrom;
  department_from: string;
  site_from: string;
  include_guests: boolean;
  interval_minutes: number | null; // null: the tenant's default (D-041), set by the server
  enabled: boolean;
}

function formFrom(directory: Directory | null): Form {
  const mapping = (directory?.mapping ?? {}) as Partial<Record<string, unknown>>;
  return {
    name: directory?.name ?? '',
    directory_tenant: directory?.directory_tenant ?? '',
    client_id: directory?.client_id ?? '',
    credential_kind: directory?.credential_kind ?? 'secret',
    credential: '',
    scope: directory?.scope ?? 'all_users',
    scope_groups: (directory?.scope_groups ?? []) as unknown as Group[],
    group_mappings: (directory?.group_mappings ?? []) as unknown as Mapped[],
    email_from: (mapping.email_from as EmailFrom | undefined) ?? 'mail',
    department_from: (mapping.department_from as string | undefined) ?? 'department',
    site_from: (mapping.site_from as string | undefined) ?? 'officeLocation',
    include_guests: mapping.include_guests === true,
    interval_minutes: directory?.interval_minutes ?? null,
    enabled: directory?.enabled ?? true,
  };
}

/** Find directory groups by name with the connector's own sync app (saved connectors only). */
function GroupPicker({
  directoryId,
  testId,
  onPick,
}: {
  directoryId: string | null;
  testId: string;
  onPick: (group: Group) => void;
}) {
  const t = useLabel();
  const [query, setQuery] = useState('');
  const found = useDirectoryGroups(directoryId, query);
  if (directoryId === null) {
    return <Typography.Text type="secondary">{t('directories.groups_after_save')}</Typography.Text>;
  }
  return (
    <Select<string>
      showSearch
      filterOption={false}
      onSearch={setQuery}
      placeholder={t('directories.find_group')}
      loading={found.isFetching}
      value={null}
      options={(found.data ?? []).map((g) => ({ value: g.external_id, label: g.name }))}
      onChange={(id) => {
        const group = (found.data ?? []).find((g) => g.external_id === id);
        if (group !== undefined) onPick({ external_id: group.external_id, name: group.name });
      }}
      notFoundContent={query === '' ? null : t('directories.no_group')}
      data-testid={testId}
      aria-label={t('directories.find_group')}
    />
  );
}

function DirectoryEditor({
  directory,
  onClose,
}: {
  directory: Directory | null;
  onClose: () => void;
}) {
  const t = useLabel();
  const create = useCreateDirectory();
  const update = useUpdateDirectory();
  const groups = useStructure('groups');
  const problem = useFormProblem();
  const [key] = useState(() => crypto.randomUUID());
  const [form, setForm] = useState<Form>(() => formFrom(directory));
  const [refused, setRefused] = useState<Record<string, string>>({});
  const editing = directory !== null;
  const set = (change: Partial<Form>) => {
    setForm({ ...form, ...change });
    setRefused({});
  };
  const ready =
    form.name.trim() !== '' &&
    form.directory_tenant.trim() !== '' &&
    form.client_id.trim() !== '' &&
    (editing || form.credential !== '') &&
    (form.scope === 'all_users' || form.scope_groups.length > 0);
  const body = (): DirectoryInput => ({
    name: form.name.trim(),
    directory_tenant: form.directory_tenant.trim(),
    client_id: form.client_id.trim(),
    credential_kind: form.credential_kind,
    ...(form.credential === '' ? {} : { credential: form.credential }),
    scope: form.scope,
    scope_groups: form.scope_groups,
    group_mappings: form.group_mappings,
    mapping: {
      email_from: form.email_from,
      department_from: form.department_from,
      site_from: form.site_from,
      include_guests: form.include_guests,
    },
    ...(form.interval_minutes === null ? {} : { interval_minutes: form.interval_minutes }),
    enabled: form.enabled,
  });
  const onError = (error: unknown) => {
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      setRefused(
        Object.fromEntries(
          error.fieldErrors.map((f) => [f.field.replace(/^body\./, ''), f.message_key]),
        ),
      );
      return;
    }
    problem.show(error);
  };
  const submit = () => {
    problem.clear();
    if (directory === null) {
      create.mutate({ body: body(), key }, { onSuccess: onClose, onError });
    } else {
      update.mutate(
        { id: directory.id, body: body(), version: directory.version },
        { onSuccess: onClose, onError },
      );
    }
  };
  const note = (name: string) =>
    refused[name] === undefined ? null : (
      <Typography.Text type="danger" id={`directory-${name}-problem`}>
        {t(refused[name])}
      </Typography.Text>
    );
  const text = (
    name: 'name' | 'directory_tenant' | 'client_id',
    labelKey: string,
    hint?: string,
  ) => (
    <Flex vertical gap={4}>
      <label htmlFor={`directory-${name}`}>{t(labelKey)}</label>
      <Input
        id={`directory-${name}`}
        value={form[name]}
        count={lengthLimit(200)}
        status={refused[name] === undefined ? undefined : 'error'}
        aria-describedby={`directory-${name}-problem`}
        onChange={(event) => {
          set({ [name]: event.target.value });
        }}
        data-testid={`directory-${name}`}
      />
      {hint !== undefined && <Typography.Text type="secondary">{t(hint)}</Typography.Text>}
      {note(name)}
    </Flex>
  );
  const groupOptions = (groups.data ?? [])
    .filter((g) => !g.disabled)
    .map((g) => ({ value: g.id, label: g.name }));

  return (
    <Drawer
      open
      width={640}
      title={t(editing ? 'directories.edit' : 'directories.add')}
      onClose={onClose}
      extra={
        <WriteButton
          type="primary"
          disabled={!ready}
          loading={create.isPending || update.isPending}
          onClick={submit}
          data-testid="directory-save"
        >
          {t('actions.save')}
        </WriteButton>
      }
    >
      <Flex vertical gap={16}>
        <FormProblem problem={problem} />
        <Alert type="info" showIcon message={t('directories.app_hint')} />
        {text('name', 'directories.name')}
        {text(
          'directory_tenant',
          'directories.directory_tenant',
          'directories.directory_tenant_hint',
        )}
        {text('client_id', 'directories.client_id')}
        <Flex vertical gap={4}>
          <label>{t('directories.credential_kind')}</label>
          <Radio.Group
            value={form.credential_kind}
            onChange={(event) => {
              set({ credential_kind: event.target.value as CredentialKind });
            }}
            options={(['secret', 'certificate'] as const).map((k) => ({
              value: k,
              label: t(`mailbox_credential_kind.${k}`),
            }))}
          />
        </Flex>
        <Flex vertical gap={4}>
          <label htmlFor="directory-credential">
            {t(`directories.credential.${form.credential_kind}`)}
          </label>
          {form.credential_kind === 'secret' ? (
            <Input.Password
              id="directory-credential"
              autoComplete="new-password"
              value={form.credential}
              onChange={(event) => {
                set({ credential: event.target.value });
              }}
              data-testid="directory-credential"
            />
          ) : (
            <Input.TextArea
              id="directory-credential"
              rows={4}
              value={form.credential}
              onChange={(event) => {
                set({ credential: event.target.value });
              }}
              data-testid="directory-credential"
            />
          )}
          {directory?.secret != null && (
            <Typography.Text type="secondary">
              {t('directories.secret_kept', {
                ending: directory.secret.ending ?? '',
              })}
            </Typography.Text>
          )}
          {note('credential')}
        </Flex>
        <Flex vertical gap={4}>
          <label>{t('directories.scope')}</label>
          <Radio.Group
            value={form.scope}
            onChange={(event) => {
              set({ scope: event.target.value as Scope });
            }}
            options={(['all_users', 'groups'] as const).map((s) => ({
              value: s,
              label: t(`sync_scope.${s}`),
            }))}
            data-testid="directory-scope"
          />
          {form.scope === 'groups' && (
            <Flex vertical gap={8}>
              {form.scope_groups.map((g) => (
                <Tag
                  key={g.external_id}
                  closable
                  onClose={() => {
                    set({
                      scope_groups: form.scope_groups.filter(
                        (x) => x.external_id !== g.external_id,
                      ),
                    });
                  }}
                >
                  {g.name}
                </Tag>
              ))}
              <GroupPicker
                directoryId={directory?.id ?? null}
                testId="directory-scope-picker"
                onPick={(group) => {
                  if (!form.scope_groups.some((x) => x.external_id === group.external_id)) {
                    set({ scope_groups: [...form.scope_groups, group] });
                  }
                }}
              />
            </Flex>
          )}
          {note('scope_groups')}
        </Flex>
        <Flex vertical gap={8}>
          <label>{t('directories.group_mappings')}</label>
          <Typography.Text type="secondary">{t('directories.group_mappings_hint')}</Typography.Text>
          {form.group_mappings.map((m, index) => (
            <Flex key={m.external_id} gap={8} align="center" wrap>
              <Typography.Text>{m.name}</Typography.Text>
              <Typography.Text type="secondary">→</Typography.Text>
              <Select<string>
                style={{ minWidth: 200 }}
                value={m.group_id === '' ? null : m.group_id}
                options={groupOptions}
                placeholder={t('directories.choose_group')}
                aria-label={t('directories.choose_group')}
                onChange={(groupId) => {
                  const next = [...form.group_mappings];
                  next[index] = { ...m, group_id: groupId };
                  set({ group_mappings: next });
                }}
              />
              <Button
                type="link"
                onClick={() => {
                  set({ group_mappings: form.group_mappings.filter((_, i) => i !== index) });
                }}
              >
                {t('actions.delete')}
              </Button>
            </Flex>
          ))}
          <GroupPicker
            directoryId={directory?.id ?? null}
            testId="directory-mapping-picker"
            onPick={(group) => {
              if (!form.group_mappings.some((x) => x.external_id === group.external_id)) {
                set({ group_mappings: [...form.group_mappings, { ...group, group_id: '' }] });
              }
            }}
          />
          {note('group_mappings')}
        </Flex>
        <Flex vertical gap={8}>
          <label>{t('directories.mapping')}</label>
          <Flex gap={8} wrap align="center">
            <Typography.Text>{t('directories.email_from')}</Typography.Text>
            <Select<EmailFrom>
              value={form.email_from}
              aria-label={t('directories.email_from')}
              onChange={(value) => {
                set({ email_from: value });
              }}
              options={(['mail', 'user_principal_name'] as const).map((v) => ({
                value: v,
                label: t(`email_from.${v}`),
              }))}
            />
          </Flex>
          {(['department_from', 'site_from'] as const).map((name) => (
            <Flex key={name} gap={8} wrap align="center">
              <Typography.Text>{t(`directories.${name}`)}</Typography.Text>
              <Select<string>
                value={form[name]}
                aria-label={t(`directories.${name}`)}
                onChange={(value) => {
                  set({ [name]: value });
                }}
                options={ATTRIBUTES.map((a) => ({
                  value: a,
                  label: t(`directory_attribute.${a}`),
                }))}
              />
            </Flex>
          ))}
          <Typography.Text type="secondary">{t('directories.mapping_hint')}</Typography.Text>
          <Flex gap={8} align="center">
            <Switch
              checked={form.include_guests}
              onChange={(value) => {
                set({ include_guests: value });
              }}
              aria-label={t('directories.include_guests')}
              style={{ alignSelf: 'flex-start' }}
            />
            <Typography.Text>{t('directories.include_guests')}</Typography.Text>
          </Flex>
        </Flex>
        <Flex vertical gap={4}>
          <label htmlFor="directory-interval">{t('directories.interval')}</label>
          <InputNumber<number>
            id="directory-interval"
            min={15}
            max={1440}
            value={form.interval_minutes}
            placeholder={t('directories.interval_default')}
            onChange={(value) => {
              set({ interval_minutes: value });
            }}
          />
          <Typography.Text type="secondary">{t('directories.interval_hint')}</Typography.Text>
          {note('interval_minutes')}
        </Flex>
        <Flex gap={8} align="center">
          <Switch
            checked={form.enabled}
            onChange={(value) => {
              set({ enabled: value });
            }}
            aria-label={t('directories.enabled')}
            style={{ alignSelf: 'flex-start' }}
          />
          <Typography.Text>{t('directories.enabled')}</Typography.Text>
        </Flex>
      </Flex>
    </Drawer>
  );
}

/**
 * Admin › Integrations › Directories (WP-040 session 2; REQ-INT-063, REQ-INT-064): who SupportX
 * takes its people from. Each directory says when it last synced, how many people it keeps and
 * what it skipped and why. Leavers are disabled, never deleted. Changes by another admin and
 * every finished run show without a reload (`integrations.directories_changed`).
 */
export function DirectoriesPage() {
  const t = useLabel();
  const dates = useDateTime();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const directories = useDirectories();
  const remove = useRemoveDirectory();
  const sync = useSyncDirectoryNow();
  const [editing, setEditing] = useState<Directory | null | undefined>();
  useTenantChannel((event) => {
    if (event.type === 'integrations.directories_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.directories.all });
    }
  });
  const items = directories.data ?? [];
  const removeIt = (directory: Directory) => {
    modal.confirm({
      title: t('directories.remove_title', { name: directory.name }),
      content: t('directories.remove_body'),
      okText: t('actions.delete'),
      okButtonProps: { danger: true },
      onOk: () => remove.mutateAsync({ id: directory.id, version: directory.version }),
    });
  };
  return (
    <Flex vertical gap={16}>
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Typography.Title level={2} style={{ margin: 0 }}>
          {t('directories.title')}
        </Typography.Title>
        <WriteButton
          type="primary"
          onClick={() => {
            setEditing(null);
          }}
          data-testid="directory-add"
        >
          {t('directories.add')}
        </WriteButton>
      </Flex>
      <Typography.Paragraph type="secondary">{t('directories.intro')}</Typography.Paragraph>
      <Table<Directory>
        rowKey="id"
        loading={directories.isLoading}
        dataSource={items}
        pagination={false}
        scroll={{ x: true }}
        locale={{ emptyText: <Empty description={t('directories.none')} /> }}
        columns={[
          {
            title: t('directories.name'),
            dataIndex: 'name',
            render: (_, d) => (
              <Flex vertical>
                <Typography.Text strong>{d.name}</Typography.Text>
                <Typography.Text type="secondary">{t(`sync_scope.${d.scope}`)}</Typography.Text>
              </Flex>
            ),
          },
          {
            title: t('directories.people'),
            dataIndex: 'people',
          },
          {
            title: t('directories.last_synced'),
            render: (_, d) =>
              d.last_synced_at === null
                ? t('directories.never_synced')
                : dates.relative(d.last_synced_at),
          },
          {
            title: t('directories.skipped'),
            render: (_, d) => {
              const skips = Object.entries(d.last_skips);
              return skips.length === 0 ? (
                t('directories.nothing_skipped')
              ) : (
                <Flex vertical>
                  {skips.map(([code, count]) => (
                    <Typography.Text key={code}>
                      {t('directories.skip_count', {
                        n: count,
                        reason: t(`directory_skip.${code}`),
                      })}
                    </Typography.Text>
                  ))}
                </Flex>
              );
            },
          },
          {
            title: t('directories.status'),
            render: (_, d) => (
              <Tag color={d.enabled ? 'green' : 'default'}>
                {t(d.enabled ? 'connector_status.active' : 'connector_status.paused')}
              </Tag>
            ),
          },
          {
            title: <span className="sx-visually-hidden">{t('directories.actions')}</span>,
            render: (_, d) => (
              <Flex gap={4} wrap>
                <WriteButton
                  disabled={!d.enabled}
                  loading={sync.isPending && sync.variables.id === d.id}
                  onClick={() => {
                    sync.mutate(
                      { id: d.id },
                      { onSuccess: () => void message.success(t('directories.sync_started')) },
                    );
                  }}
                  data-testid={`directory-sync-${d.id}`}
                >
                  {t('directories.sync_now')}
                </WriteButton>
                <Button
                  onClick={() => {
                    setEditing(d);
                  }}
                  data-testid={`directory-edit-${d.id}`}
                >
                  {t('actions.edit')}
                </Button>
                <WriteButton
                  danger
                  onClick={() => {
                    removeIt(d);
                  }}
                  data-testid={`directory-remove-${d.id}`}
                >
                  {t('actions.delete')}
                </WriteButton>
              </Flex>
            ),
          },
        ]}
      />
      {editing !== undefined && (
        <DirectoryEditor
          directory={editing}
          onClose={() => {
            setEditing(undefined);
          }}
        />
      )}
    </Flex>
  );
}
