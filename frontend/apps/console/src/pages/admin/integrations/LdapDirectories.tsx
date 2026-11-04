import {
  Alert,
  App,
  Button,
  Checkbox,
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
import { useState } from 'react';

import {
  ApiError,
  useCreateLdapDirectory,
  useLdapDirectories,
  useRemoveLdapDirectory,
  useUpdateLdapDirectory,
  type LdapDirectory,
  type LdapDirectoryInput,
} from '@supportx/api-client';
import {
  FormProblem,
  lengthLimit,
  markHandled,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

// WP-040 (D-118): AD/LDAP directories, connected through the identity service. Only where the
// installation turned AD/LDAP on and the licence has the add-on: otherwise the server says why
// (a code with a label), and the section shows that instead of the list.

type Security = NonNullable<LdapDirectoryInput['security']>;
type Vendor = NonNullable<LdapDirectoryInput['vendor']>;
const SECURITY: Security[] = ['ldaps', 'start_tls', 'plain'];
const VENDORS: Vendor[] = ['ad', 'other'];
const STATE_COLOUR: Record<string, string> = {
  applied: 'green',
  pending: 'blue',
  failed: 'red',
};

interface Form {
  name: string;
  host: string;
  port: number | null;
  security: Security;
  allow_plain: boolean;
  vendor: Vendor;
  bind_dn: string;
  bind_password: string;
  users_dn: string;
  groups_dn: string;
  user_filter: string;
  department_from: string;
  site_from: string;
  changed_minutes: number;
  full_hours: number;
  enabled: boolean;
}

const text = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

function formFrom(directory: LdapDirectory | null): Form {
  const s = directory?.settings ?? {};
  return {
    name: directory?.name ?? '',
    host: text(s.host),
    port: typeof s.port === 'number' ? s.port : null,
    security: text(s.security, 'ldaps') as Security,
    allow_plain: s.allow_plain === true,
    vendor: text(s.vendor, 'ad') as Vendor,
    bind_dn: text(s.bind_dn),
    bind_password: '',
    users_dn: text(s.users_dn),
    groups_dn: text(s.groups_dn),
    user_filter: text(s.user_filter),
    department_from: text(s.department_from, 'department'),
    site_from: text(s.site_from, 'physicalDeliveryOfficeName'),
    changed_minutes: typeof s.changed_sync_seconds === 'number' ? s.changed_sync_seconds / 60 : 30,
    full_hours: typeof s.full_sync_seconds === 'number' ? s.full_sync_seconds / 3600 : 24,
    enabled: directory?.enabled ?? true,
  };
}

const optional = (value: string) => (value.trim() === '' ? null : value.trim());

function LdapEditor({
  directory,
  onClose,
}: {
  directory: LdapDirectory | null;
  onClose: () => void;
}) {
  const t = useLabel();
  const create = useCreateLdapDirectory();
  const update = useUpdateLdapDirectory();
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
    form.host.trim() !== '' &&
    form.bind_dn.trim() !== '' &&
    form.users_dn.trim() !== '' &&
    (editing || form.bind_password !== '') &&
    (form.security !== 'plain' || form.allow_plain);
  const body = (): LdapDirectoryInput => ({
    name: form.name.trim(),
    host: form.host.trim(),
    port: form.port,
    security: form.security,
    allow_plain: form.security === 'plain' && form.allow_plain,
    vendor: form.vendor,
    bind_dn: form.bind_dn.trim(),
    ...(form.bind_password === '' ? {} : { bind_password: form.bind_password }),
    users_dn: form.users_dn.trim(),
    groups_dn: optional(form.groups_dn),
    user_filter: optional(form.user_filter),
    department_from: form.department_from.trim(),
    site_from: form.site_from.trim(),
    changed_sync_seconds: Math.round(form.changed_minutes * 60),
    full_sync_seconds: Math.round(form.full_hours * 3600),
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
      <Typography.Text type="danger" id={`ldap-${name}-problem`}>
        {t(refused[name])}
      </Typography.Text>
    );
  type TextField =
    | 'name'
    | 'host'
    | 'bind_dn'
    | 'users_dn'
    | 'groups_dn'
    | 'user_filter'
    | 'department_from'
    | 'site_from';
  const field = (name: TextField, hint?: string) => (
    <Flex vertical gap={4}>
      <label htmlFor={`ldap-${name}`}>{t(`ldap_directories.${name}`)}</label>
      <Input
        id={`ldap-${name}`}
        value={form[name]}
        count={lengthLimit(name === 'name' ? 200 : 500)}
        status={refused[name] === undefined ? undefined : 'error'}
        aria-describedby={`ldap-${name}-problem`}
        onChange={(event) => {
          set({ [name]: event.target.value });
        }}
        data-testid={`ldap-${name}`}
      />
      {hint !== undefined && <Typography.Text type="secondary">{t(hint)}</Typography.Text>}
      {note(name)}
    </Flex>
  );

  return (
    <Drawer
      open
      width={640}
      title={t(editing ? 'ldap_directories.edit' : 'ldap_directories.add')}
      onClose={onClose}
      extra={
        <WriteButton
          type="primary"
          disabled={!ready}
          loading={create.isPending || update.isPending}
          onClick={submit}
          data-testid="ldap-save"
        >
          {t('actions.save')}
        </WriteButton>
      }
    >
      <Flex vertical gap={16}>
        <FormProblem problem={problem} />
        {field('name')}
        <Flex vertical gap={4}>
          <span id="ldap-vendor-label">{t('ldap_directories.vendor')}</span>
          <Select
            aria-labelledby="ldap-vendor-label"
            value={form.vendor}
            options={VENDORS.map((v) => ({ value: v, label: t(`ldap_vendor.${v}`) }))}
            onChange={(vendor) => {
              set({ vendor });
            }}
            data-testid="ldap-vendor"
          />
        </Flex>
        {field('host', 'ldap_directories.host_hint')}
        <Flex vertical gap={4}>
          <span id="ldap-security-label">{t('ldap_directories.security')}</span>
          <Radio.Group
            aria-labelledby="ldap-security-label"
            value={form.security}
            onChange={(event) => {
              set({ security: event.target.value as Security, port: null });
            }}
            data-testid="ldap-security"
          >
            <Flex vertical gap={4}>
              {SECURITY.map((s) => (
                <Radio key={s} value={s}>
                  {t(`ldap_security.${s}`)}
                </Radio>
              ))}
            </Flex>
          </Radio.Group>
          {note('security')}
        </Flex>
        {form.security === 'plain' && (
          <Alert
            type="warning"
            showIcon
            message={t('ldap_directories.plain_warning')}
            description={
              <Checkbox
                checked={form.allow_plain}
                onChange={(event) => {
                  set({ allow_plain: event.target.checked });
                }}
                data-testid="ldap-allow-plain"
              >
                {t('ldap_directories.allow_plain')}
              </Checkbox>
            }
          />
        )}
        <Flex vertical gap={4}>
          <label htmlFor="ldap-port">{t('ldap_directories.port')}</label>
          <InputNumber
            id="ldap-port"
            min={1}
            max={65535}
            value={form.port}
            placeholder={form.security === 'ldaps' ? '636' : '389'}
            onChange={(port) => {
              set({ port });
            }}
            data-testid="ldap-port"
          />
          {note('port')}
        </Flex>
        {field('bind_dn', 'ldap_directories.bind_dn_hint')}
        <Flex vertical gap={4}>
          <label htmlFor="ldap-bind_password">{t('ldap_directories.bind_password')}</label>
          <Input.Password
            id="ldap-bind_password"
            autoComplete="new-password"
            value={form.bind_password}
            placeholder={editing ? t('ldap_directories.password_kept') : undefined}
            onChange={(event) => {
              set({ bind_password: event.target.value });
            }}
            data-testid="ldap-bind_password"
          />
          {note('bind_password')}
        </Flex>
        {field('users_dn', 'ldap_directories.users_dn_hint')}
        {field('groups_dn', 'ldap_directories.groups_dn_hint')}
        {field('user_filter', 'ldap_directories.user_filter_hint')}
        {field('department_from')}
        {field('site_from')}
        <Flex gap={16} wrap>
          <Flex vertical gap={4}>
            <label htmlFor="ldap-changed">{t('ldap_directories.changed_minutes')}</label>
            <InputNumber
              id="ldap-changed"
              min={5}
              max={1440}
              value={form.changed_minutes}
              onChange={(value) => {
                set({ changed_minutes: value ?? 30 });
              }}
            />
          </Flex>
          <Flex vertical gap={4}>
            <label htmlFor="ldap-full">{t('ldap_directories.full_hours')}</label>
            <InputNumber
              id="ldap-full"
              min={1}
              max={168}
              value={form.full_hours}
              onChange={(value) => {
                set({ full_hours: value ?? 24 });
              }}
            />
          </Flex>
        </Flex>
        <Flex gap={8} align="center">
          <Switch
            id="ldap-enabled"
            checked={form.enabled}
            onChange={(enabled) => {
              set({ enabled });
            }}
          />
          <label htmlFor="ldap-enabled">{t('ldap_directories.enabled')}</label>
        </Flex>
      </Flex>
    </Drawer>
  );
}

/** Admin › Integrations › Directories: the AD/LDAP part. */
export function LdapDirectories() {
  const t = useLabel();
  const { modal } = App.useApp();
  const directories = useLdapDirectories();
  const remove = useRemoveLdapDirectory();
  const [editing, setEditing] = useState<LdapDirectory | null | undefined>();
  const unavailable =
    directories.error instanceof ApiError &&
    [403, 409, 503].includes(directories.error.status) &&
    directories.error.code !== 'permission_denied'
      ? directories.error.code
      : null;
  const removeIt = (directory: LdapDirectory) => {
    modal.confirm({
      title: t('ldap_directories.remove_title', { name: directory.name }),
      content: t('ldap_directories.remove_body'),
      okText: t('actions.delete'),
      okButtonProps: { danger: true },
      onOk: () => remove.mutateAsync({ id: directory.id, version: directory.version }),
    });
  };
  return (
    <Flex vertical gap={8}>
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {t('ldap_directories.title')}
        </Typography.Title>
        {unavailable === null && (
          <WriteButton
            onClick={() => {
              setEditing(null);
            }}
            data-testid="ldap-add"
          >
            {t('ldap_directories.add')}
          </WriteButton>
        )}
      </Flex>
      <Typography.Paragraph type="secondary">{t('ldap_directories.intro')}</Typography.Paragraph>
      {unavailable !== null ? (
        <Alert type="info" showIcon message={t(`errors.${unavailable}`)} data-testid="ldap-off" />
      ) : (
        <Table<LdapDirectory>
          rowKey="id"
          loading={directories.isLoading}
          dataSource={directories.data ?? []}
          pagination={false}
          scroll={{ x: true }}
          locale={{ emptyText: <Empty description={t('ldap_directories.none')} /> }}
          columns={[
            {
              title: t('ldap_directories.name'),
              render: (_, d) => (
                <Flex vertical>
                  <Typography.Text strong>{d.name}</Typography.Text>
                  <Typography.Text type="secondary">
                    {t(`ldap_security.${text(d.settings.security, 'ldaps')}`)}
                  </Typography.Text>
                </Flex>
              ),
            },
            { title: t('directories.people'), dataIndex: 'people' },
            {
              title: t('ldap_directories.connection'),
              render: (_, d) => (
                <Flex vertical gap={4}>
                  <Tag color={STATE_COLOUR[d.federation_state ?? 'pending'] ?? 'default'}>
                    {t(`federation_state.${d.federation_state ?? 'pending'}`)}
                  </Tag>
                  {d.federation_error !== null && (
                    <Typography.Text type="danger">
                      {t(`errors.${d.federation_error}`)}
                    </Typography.Text>
                  )}
                </Flex>
              ),
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
                  <Button
                    onClick={() => {
                      setEditing(d);
                    }}
                    data-testid={`ldap-edit-${d.id}`}
                  >
                    {t('actions.edit')}
                  </Button>
                  <WriteButton
                    danger
                    onClick={() => {
                      removeIt(d);
                    }}
                    data-testid={`ldap-remove-${d.id}`}
                  >
                    {t('actions.delete')}
                  </WriteButton>
                </Flex>
              ),
            },
          ]}
        />
      )}
      {editing !== undefined && (
        <LdapEditor
          directory={editing}
          onClose={() => {
            setEditing(undefined);
          }}
        />
      )}
    </Flex>
  );
}
