import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Flex,
  Form,
  Input,
  Modal,
  Radio,
  Select,
  Space,
  Table,
  Typography,
} from 'antd';
import { type ReactNode, useMemo, useState } from 'react';

import {
  type ApiKey,
  type ApiKeyCreated,
  type ApiKeyRules,
  type ApiKeyScope,
  useApiKeyOwners,
  useApiKeyRules,
  useApiKeys,
  useApiKeyScopes,
  useCreateApiKey,
  useRevokeApiKey,
  useSession,
} from '@supportx/api-client';
import { useListChannel, usePersonalChannel, useTenantChannel } from '@supportx/realtime';
import {
  DateTimeField,
  EmptyText,
  lengthLimit,
  reportError,
  ToneTag,
  type Tone,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { showFieldErrors } from '../knowledge/formErrors';
import { type Access, scopesOf } from './scopes';

// WP-041 (D-128): API keys, for key managers (every key, any owner) and for people's own keys
// when the organisation allows them. The key text is shown once, in a dialog, and kept nowhere.

type Mode = 'admin' | 'mine';

const STATUS_TONE: Record<ApiKey['status'], Tone> = {
  active: 'success',
  expired: 'default',
  revoked: 'error',
};

interface KeyForm {
  name: string;
  owner_id: string;
  access: Record<string, Access>;
  expires_at: string | null;
  never_expires: boolean;
  ip_allowlist: string;
}

function useScopeText() {
  const t = useLabel();
  return (code: string) => {
    const [area = '', kind] = code.split(':');
    return t('api_keys.scope', {
      area: t(`permission_module.${area}`),
      access: t(kind === 'write' ? 'api_keys.access.write' : 'api_keys.access.read'),
    });
  };
}

/** A key's scopes shown per area: "Incidents: read and write" rather than two entries. */
function ScopeList({ scopes }: { scopes: string[] }) {
  const text = useScopeText();
  const shown = scopes.filter(
    (s) => !(s.endsWith(':read') && scopes.includes(s.replace(':read', ':write'))),
  );
  return (
    <Flex wrap gap={4}>
      {shown.map((scope) => (
        <ToneTag key={scope} tone="default">
          {text(scope)}
        </ToneTag>
      ))}
    </Flex>
  );
}

/** Service identities a key manager may make keys for (people with user type "service"). */
function OwnerSelect({
  id,
  value,
  onChange,
}: {
  id?: string; // from Form.Item: the label points at it (axe: label)
  value?: string;
  onChange?: (value: string) => void;
}) {
  const t = useLabel();
  const me = useSession().data?.user.id ?? '';
  const services = useApiKeyOwners();
  const rows = services.data ?? [];
  return (
    <Select
      id={id}
      value={value}
      onChange={onChange}
      loading={services.isPending}
      data-testid="api-key-owner"
      options={[
        { value: me, label: t('api_keys.form.owner_me') },
        ...rows.map((user) => ({ value: user.id, label: user.display_name })),
      ]}
    />
  );
}

/**
 * The scope rows' box as a form control. Form.Item hands its child `aria-required`, which a
 * plain box may not carry (axe: aria-allowed-attr), so the box is a named group and keeps only
 * the error link and state. Each row's radio group is the required control.
 */
function ScopesBox({
  id,
  label,
  children,
  'aria-describedby': describedBy,
  'aria-invalid': invalid,
}: {
  id?: string;
  label: string;
  children: ReactNode;
  'aria-describedby'?: string;
  'aria-invalid'?: boolean | 'true' | 'false';
}) {
  return (
    <div
      id={id}
      role="group"
      aria-label={label}
      aria-describedby={describedBy}
      aria-invalid={invalid}
      data-testid="api-key-scopes"
      style={{
        maxHeight: 280,
        overflowY: 'auto',
        border: '1px solid var(--ant-color-border-secondary)',
        borderRadius: 6,
        padding: 8,
      }}
    >
      {children}
    </div>
  );
}

/** The expiry picker as a form control (Form.Item passes value and onChange). */
function ExpiryField({
  value,
  onChange,
  disabled,
}: {
  value?: string | null;
  onChange?: (value: string | null) => void;
  disabled?: boolean;
}) {
  return (
    <DateTimeField
      value={value ?? null}
      onChange={(next) => onChange?.(next)}
      disabled={disabled}
      testId="api-key-expires"
    />
  );
}

function NewKeyDialog({
  mode,
  rules,
  scopes,
  onClose,
  onMade,
}: {
  mode: Mode;
  rules: ApiKeyRules;
  scopes: ApiKeyScope[];
  onClose: () => void;
  onMade: (made: ApiKeyCreated) => void;
}) {
  const t = useLabel();
  const me = useSession().data?.user.id ?? '';
  const [form] = Form.useForm<KeyForm>();
  const [key] = useState(() => crypto.randomUUID());
  const create = useCreateApiKey();
  const never = Form.useWatch('never_expires', form) as boolean | undefined;
  const areas = useMemo(() => [...new Set(scopes.map((s) => s.area))].sort(), [scopes]);

  const save = (values: KeyForm) => {
    create.mutate(
      {
        key,
        body: {
          name: values.name.trim(),
          owner_id: values.owner_id === me ? null : values.owner_id,
          scopes: scopesOf(values.access),
          expires_at: values.never_expires ? null : values.expires_at,
          never_expires: values.never_expires,
          ip_allowlist: values.ip_allowlist
            .split(/[\n,]/)
            .map((line) => line.trim())
            .filter((line) => line !== ''),
        },
      },
      {
        onSuccess: onMade,
        onError: (error) => {
          if (!showFieldErrors(form, error, t)) reportError(error);
        },
      },
    );
  };

  return (
    <Modal
      open
      title={t('api_keys.form.title')}
      onCancel={onClose}
      width={640}
      footer={null}
      destroyOnHidden
      data-testid="api-key-new"
    >
      <Form<KeyForm>
        form={form}
        layout="vertical"
        initialValues={{
          name: '',
          owner_id: me,
          access: Object.fromEntries(areas.map((area) => [area, 'none'])),
          expires_at: null,
          never_expires: false,
          ip_allowlist: '',
        }}
        onFinish={save}
      >
        <Form.Item
          name="name"
          label={t('api_keys.form.name')}
          extra={t('api_keys.form.name_help')}
          rules={[
            { required: true, whitespace: true, message: t('errors.field.api_key_name_invalid') },
          ]}
        >
          <Input count={lengthLimit(100)} dir="auto" data-testid="api-key-name" />
        </Form.Item>
        {mode === 'admin' && rules.manages_keys && (
          <Form.Item
            name="owner_id"
            label={t('api_keys.form.owner')}
            extra={t('api_keys.form.owner_help')}
          >
            <OwnerSelect />
          </Form.Item>
        )}
        <Form.Item
          name="scopes"
          label={t('api_keys.form.scopes')}
          extra={t('api_keys.form.scopes_help')}
          required
          rules={[
            {
              validator: () =>
                scopesOf((form.getFieldValue('access') ?? {}) as Record<string, Access>).length > 0
                  ? Promise.resolve()
                  : Promise.reject(new Error(t('api_keys.form.scopes_required'))),
            },
          ]}
        >
          <ScopesBox label={t('api_keys.form.scopes')}>
            {areas.map((area) => (
              <Flex
                key={area}
                justify="space-between"
                align="center"
                gap={8}
                wrap
                style={{ paddingBlock: 4 }}
              >
                <Typography.Text id={`api-key-area-${area}`}>
                  {t(`permission_module.${area}`)}
                </Typography.Text>
                <Form.Item name={['access', area]} noStyle>
                  <Radio.Group
                    size="small"
                    optionType="button"
                    aria-labelledby={`api-key-area-${area}`}
                    data-testid={`api-key-scope-${area}`}
                    onChange={() => void form.validateFields(['scopes'])}
                    options={(['none', 'read', 'write'] as const).map((level) => ({
                      value: level,
                      label: t(`api_keys.access.${level}`),
                    }))}
                  />
                </Form.Item>
              </Flex>
            ))}
          </ScopesBox>
        </Form.Item>
        <Flex gap={16} wrap align="start">
          <Form.Item
            name="expires_at"
            label={t('api_keys.form.expires')}
            extra={t('api_keys.form.expires_help', {
              days: rules.default_lifetime_days,
              max: rules.max_lifetime_days,
            })}
            style={{ flex: '1 1 260px' }}
          >
            <ExpiryField disabled={never === true} />
          </Form.Item>
          {rules.never_expires_allowed && (
            <Form.Item
              name="never_expires"
              valuePropName="checked"
              label=" "
              style={{ flex: '0 0 auto' }}
            >
              <Checkbox data-testid="api-key-never">{t('api_keys.form.never_expires')}</Checkbox>
            </Form.Item>
          )}
        </Flex>
        <Form.Item
          name="ip_allowlist"
          label={t('api_keys.form.allowlist')}
          extra={t('api_keys.form.allowlist_help')}
        >
          <Input.TextArea rows={3} dir="ltr" data-testid="api-key-allowlist" />
        </Form.Item>
        <Space>
          <WriteButton
            type="primary"
            htmlType="submit"
            loading={create.isPending}
            data-testid="api-key-create"
          >
            {t('api_keys.form.create')}
          </WriteButton>
          <Button onClick={onClose}>{t('actions.cancel')}</Button>
        </Space>
      </Form>
    </Modal>
  );
}

/** The one time the whole key is shown (REQ-INT-019 AC1). Closing it forgets the text. */
function ShownOnce({ made, onClose }: { made: ApiKeyCreated; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  return (
    <Modal
      open
      title={t('api_keys.shown.title')}
      closable={false}
      maskClosable={false}
      keyboard={false}
      footer={
        <Button type="primary" onClick={onClose} data-testid="api-key-shown-done">
          {t('api_keys.shown.done')}
        </Button>
      }
      data-testid="api-key-shown"
    >
      {made.key === null ? (
        <Alert type="warning" showIcon message={t('api_keys.shown.replay')} />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Paragraph>{t('api_keys.shown.explain')}</Typography.Paragraph>
          <Space.Compact style={{ width: '100%' }}>
            <Input
              readOnly
              value={made.key}
              dir="ltr"
              aria-label={t('api_keys.shown.title')}
              data-testid="api-key-text"
              style={{ fontFamily: 'monospace' }}
            />
            <Button
              data-testid="api-key-copy"
              onClick={() => {
                void navigator.clipboard
                  .writeText(made.key ?? '')
                  .then(() => void message.success(t('api_keys.shown.copied')));
              }}
            >
              {t('api_keys.shown.copy')}
            </Button>
          </Space.Compact>
        </Space>
      )}
    </Modal>
  );
}

/**
 * The key list with its actions. `admin`: every key (Admin › API keys, api_keys.manage), live on
 * the api_keys list channel. `mine`: your own keys (My profile), live on your own channel.
 */
export function ApiKeysPanel({ mode }: { mode: Mode }) {
  const t = useLabel();
  const dates = useDateTime();
  const { modal, message } = App.useApp();
  const rules = useApiKeyRules();
  const myId = useSession().data?.user.id ?? '';
  const keys = useApiKeys(rules.data !== undefined);
  const scopes = useApiKeyScopes(rules.data?.may_create === true);
  const revoke = useRevokeApiKey();
  const [creating, setCreating] = useState(false);
  const [made, setMade] = useState<ApiKeyCreated | null>(null);

  const refetch = () => void keys.refetch();
  useListChannel(
    mode === 'admin' && rules.data?.manages_keys === true ? 'api_keys' : null,
    refetch,
  );
  usePersonalChannel((m) => {
    if (m.type === 'api_keys.changed') refetch();
  });
  useTenantChannel((m) => {
    if (m.type === 'api_keys.rules_changed') void rules.refetch();
  });

  if (rules.data === undefined) return null;
  if (mode === 'mine' && !rules.data.may_create && (keys.data ?? []).length === 0) return null;
  const me = mode === 'mine';
  // A key manager's list holds every key; My profile shows only one's own.
  const rows = (keys.data ?? []).filter((row) => !me || row.owner_id === myId);

  return (
    <Card
      title={t('api_keys.title')}
      data-testid={`api-keys-${mode}`}
      extra={
        rules.data.may_create && (
          <WriteButton
            onClick={() => {
              setCreating(true);
            }}
            data-testid="api-key-new-open"
          >
            {t('api_keys.new')}
          </WriteButton>
        )
      }
    >
      <Typography.Paragraph type="secondary">
        {t(me ? 'api_keys.intro_mine' : 'api_keys.intro_admin')}
      </Typography.Paragraph>
      <Table<ApiKey>
        rowKey="id"
        size="small"
        loading={keys.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyText>{t('api_keys.empty')}</EmptyText> }}
        columns={[
          {
            title: t('api_keys.col.name'),
            key: 'name',
            render: (_, row) => (
              <Space direction="vertical" size={0}>
                <Typography.Text strong>{row.name}</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('api_keys.ends_in', { last: row.last_four })}
                </Typography.Text>
              </Space>
            ),
          },
          ...(me
            ? []
            : [
                {
                  title: t('api_keys.col.owner'),
                  key: 'owner',
                  render: (_: unknown, row: ApiKey) => row.owner_name ?? '',
                },
              ]),
          {
            title: t('api_keys.col.scopes'),
            key: 'scopes',
            render: (_, row) => <ScopeList scopes={row.scopes} />,
          },
          {
            title: t('api_keys.col.expires'),
            key: 'expires',
            render: (_, row) =>
              row.expires_at === null ? t('api_keys.no_expiry') : dates.format(row.expires_at),
          },
          {
            title: t('api_keys.col.last_used'),
            key: 'used',
            render: (_, row) =>
              row.last_used_at === null
                ? t('api_keys.not_used')
                : row.last_used_ip === null
                  ? dates.format(row.last_used_at)
                  : t('api_keys.used_from', {
                      when: dates.format(row.last_used_at),
                      address: row.last_used_ip,
                    }),
          },
          {
            title: t('api_keys.col.status'),
            key: 'status',
            render: (_, row) => (
              <ToneTag tone={STATUS_TONE[row.status]}>{t(`api_key_status.${row.status}`)}</ToneTag>
            ),
          },
          {
            title: '',
            key: 'actions',
            render: (_, row) =>
              row.status === 'active' && (
                <WriteButton
                  danger
                  size="small"
                  data-testid={`api-key-revoke-${row.last_four}`}
                  onClick={() => {
                    modal.confirm({
                      title: t('api_keys.revoke_confirm', { name: row.name }),
                      okText: t('api_keys.revoke'),
                      okButtonProps: { danger: true },
                      cancelText: t('actions.cancel'),
                      onOk: () =>
                        revoke
                          .mutateAsync(row.id)
                          .then(() => void message.success(t('api_keys.revoked'))),
                    });
                  }}
                >
                  {t('api_keys.revoke')}
                </WriteButton>
              ),
          },
        ]}
      />
      {creating && scopes.data !== undefined && (
        <NewKeyDialog
          mode={mode}
          rules={rules.data}
          scopes={scopes.data}
          onClose={() => {
            setCreating(false);
          }}
          onMade={(answer) => {
            setCreating(false);
            setMade(answer);
          }}
        />
      )}
      {made !== null && (
        <ShownOnce
          made={made}
          onClose={() => {
            setMade(null);
          }}
        />
      )}
    </Card>
  );
}
