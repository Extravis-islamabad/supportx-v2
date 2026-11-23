import {
  Alert,
  App,
  Button,
  Checkbox,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Space,
  Switch,
  Table,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useAddSiemDestination,
  useChangeSiemDestination,
  useRemoveSiemDestination,
  useRotateSiemSecret,
  useSiemDestinations,
  useTestSiemDestination,
  type SiemDestination,
  type SiemDestinationInput,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  EditDrawer,
  EmptyText,
  FormProblem,
  lengthLimit,
  markHandled,
  ToneTag,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

const SYSLOG_PORT = 6514; // RFC 5425: syslog over TLS
const PLAIN_PORT = 514; // plain syslog (D-181: only by an admin's choice)
const UDP_MAX_DEFAULT = 2048;

interface Values {
  name: string;
  kind: SiemDestinationInput['kind'];
  format: NonNullable<SiemDestinationInput['format']>;
  host?: string;
  port?: number;
  url?: string;
  streams: NonNullable<SiemDestinationInput['streams']>;
  enabled: boolean;
  ca_pem?: string;
  client_cert_pem?: string;
  client_key_pem?: string;
  transport: NonNullable<SiemDestinationInput['transport']>;
  udp_max_bytes?: number;
}

function body(values: Values): SiemDestinationInput {
  const pem = (value: string | undefined) =>
    value === undefined || value.trim() === '' ? undefined : value;
  const syslog = values.kind === 'syslog';
  return {
    name: values.name.trim(),
    kind: values.kind,
    format: syslog ? values.format : 'json',
    host: syslog ? (values.host ?? '').trim() : null,
    port: syslog ? (values.port ?? SYSLOG_PORT) : null,
    url: syslog ? null : (values.url ?? '').trim(),
    streams: values.streams,
    enabled: values.enabled,
    ca_pem: pem(values.ca_pem),
    client_cert_pem: pem(values.client_cert_pem),
    client_key_pem: pem(values.client_key_pem),
    // D-181: a webhook is always HTTPS; plain TCP or UDP only for syslog.
    transport: syslog ? values.transport : 'tls',
    udp_max_bytes: values.udp_max_bytes ?? UDP_MAX_DEFAULT,
  };
}

/** The signing secret, shown once (a new webhook, or a rotation's new secret). */
function SecretDialog({ secret, onClose }: { secret: string; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  return (
    <Modal
      open
      title={t('siem.secret.title')}
      closable={false}
      maskClosable={false}
      keyboard={false}
      footer={
        <Button type="primary" onClick={onClose} data-testid="siem-secret-done">
          {t('siem.secret.done')}
        </Button>
      }
      data-testid="siem-secret"
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Paragraph>{t('siem.secret.explain')}</Typography.Paragraph>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            readOnly
            value={secret}
            dir="ltr"
            style={{ fontFamily: 'monospace' }}
            aria-label={t('siem.secret.title')}
          />
          <Button
            onClick={() => {
              void navigator.clipboard
                .writeText(secret)
                .then(() => void message.success(t('siem.secret.copied')));
            }}
          >
            {t('siem.secret.copy')}
          </Button>
        </Space.Compact>
      </Space>
    </Modal>
  );
}

function DestinationDrawer({
  editing,
  open,
  onClose,
  onSecret,
}: {
  editing: SiemDestination | null;
  open: boolean;
  onClose: () => void;
  onSecret: (secret: string) => void;
}) {
  const t = useLabel();
  const [form] = Form.useForm<Values>();
  const add = useAddSiemDestination();
  const change = useChangeSiemDestination();
  const problem = useFormProblem();
  const [key, setKey] = useState(() => crypto.randomUUID());
  // Undefined until the form mounts (antd's type says otherwise).
  const watched = Form.useWatch('kind', form) as Values['kind'] | undefined;
  const kind = watched ?? editing?.kind ?? 'syslog';
  const watchedTransport = Form.useWatch('transport', form) as Values['transport'] | undefined;
  const transport = watchedTransport ?? editing?.transport ?? 'tls';
  const initial: Values = editing
    ? {
        name: editing.name,
        kind: editing.kind,
        format: editing.format,
        host: editing.host ?? undefined,
        port: editing.port ?? undefined,
        url: editing.url ?? undefined,
        streams: editing.streams,
        enabled: editing.enabled,
        transport: editing.transport,
        udp_max_bytes: editing.udp_max_bytes,
      }
    : {
        name: '',
        kind: 'syslog',
        format: 'cef',
        port: SYSLOG_PORT,
        streams: ['audit'],
        enabled: true,
        transport: 'tls',
        udp_max_bytes: UDP_MAX_DEFAULT,
      };
  const close = () => {
    form.resetFields();
    problem.clear();
    setKey(crypto.randomUUID());
    onClose();
  };
  const refused = (error: unknown) => {
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      form.setFields(
        error.fieldErrors.map((f) => ({
          name: f.field.replace(/^body\./, '') as keyof Values,
          errors: [t(f.message_key, f.params ?? {})],
        })),
      );
      return;
    }
    problem.show(error);
  };
  const submit = async () => {
    problem.clear();
    const values = await form.validateFields();
    if (editing) {
      change.mutate(
        { id: editing.id, version: editing.version, body: body(values) },
        { onSuccess: close, onError: refused },
      );
    } else {
      add.mutate(
        { body: body(values), key },
        {
          onSuccess: (made) => {
            close();
            if (made.secret) onSecret(made.secret);
            add.reset(); // the secret is gone from the mutation too
          },
          onError: refused,
        },
      );
    }
  };
  return (
    <EditDrawer
      open={open}
      title={editing ? t('siem.drawer.edit', { name: editing.name }) : t('siem.drawer.add')}
      okText={editing ? t('siem.drawer.save') : t('siem.drawer.add_ok')}
      saving={add.isPending || change.isPending}
      onCancel={close}
      onOk={() => {
        void submit();
      }}
      testId="siem-drawer"
    >
      <FormProblem problem={problem} />
      <Form<Values> form={form} layout="vertical" initialValues={initial} requiredMark>
        <Form.Item
          name="name"
          label={t('siem.field.name')}
          rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
        >
          <Input count={lengthLimit(100)} data-testid="siem-name" />
        </Form.Item>
        <Form.Item name="kind" label={t('siem.field.kind')}>
          <Radio.Group disabled={editing !== null}>
            <Radio value="syslog">{t('siem_destination_kind.syslog')}</Radio>
            <Radio value="webhook">{t('siem_destination_kind.webhook')}</Radio>
          </Radio.Group>
        </Form.Item>
        {kind === 'syslog' ? (
          <>
            <Form.Item
              name="host"
              label={t('siem.field.host')}
              rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
            >
              <Input dir="ltr" count={lengthLimit(253)} data-testid="siem-host" />
            </Form.Item>
            <Form.Item name="transport" label={t('siem.field.transport')}>
              <Radio.Group
                onChange={(event) => {
                  // The usual port for the transport, unless the admin set their own.
                  const port = form.getFieldValue('port') as number | undefined;
                  if (port === SYSLOG_PORT || port === PLAIN_PORT || port === undefined) {
                    form.setFieldValue(
                      'port',
                      event.target.value === 'tls' ? SYSLOG_PORT : PLAIN_PORT,
                    );
                  }
                }}
                data-testid="siem-transport"
              >
                <Radio value="tls">{t('siem_transport.tls')}</Radio>
                <Radio value="tcp">{t('siem_transport.tcp')}</Radio>
                <Radio value="udp">{t('siem_transport.udp')}</Radio>
              </Radio.Group>
            </Form.Item>
            {transport !== 'tls' && (
              <Alert
                type="warning"
                showIcon
                message={t('siem.plaintext.title')}
                description={t(
                  transport === 'udp' ? 'siem.plaintext.body_udp' : 'siem.plaintext.body_tcp',
                )}
                data-testid="siem-plaintext-warning"
                style={{ marginBottom: 16 }}
              />
            )}
            <Form.Item name="port" label={t('siem.field.port')} extra={t('siem.field.port_help')}>
              <InputNumber min={1} max={65535} precision={0} style={{ width: 168 }} />
            </Form.Item>
            {transport === 'udp' && (
              <Form.Item
                name="udp_max_bytes"
                label={t('siem.field.udp_max_bytes')}
                extra={t('siem.field.udp_max_bytes_help')}
              >
                <InputNumber min={480} max={8192} precision={0} style={{ width: 168 }} />
              </Form.Item>
            )}
            <Form.Item name="format" label={t('siem.field.format')}>
              <Radio.Group>
                <Radio value="cef">{t('siem_format.cef')}</Radio>
                <Radio value="json">{t('siem_format.json')}</Radio>
              </Radio.Group>
            </Form.Item>
          </>
        ) : (
          <Form.Item
            name="url"
            label={t('siem.field.url')}
            extra={t('siem.field.url_help')}
            rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
          >
            <Input dir="ltr" count={lengthLimit(2048)} data-testid="siem-url" />
          </Form.Item>
        )}
        <Form.Item
          name="streams"
          label={t('siem.field.streams')}
          rules={[{ required: true, message: t('errors.field.required') }]}
        >
          <Checkbox.Group
            options={[
              { value: 'audit', label: t('siem_stream.audit') },
              { value: 'sign_ins', label: t('siem_stream.sign_ins') },
            ]}
          />
        </Form.Item>
        <Form.Item name="enabled" label={t('siem.field.enabled')} valuePropName="checked">
          <Switch />
        </Form.Item>
        <Typography.Title level={5}>{t('siem.field.tls')}</Typography.Title>
        <Typography.Paragraph type="secondary">{t('siem.field.tls_help')}</Typography.Paragraph>
        <Form.Item
          name="ca_pem"
          label={t('siem.field.ca_pem')}
          extra={editing?.has_ca ? t('siem.field.set_keep') : undefined}
        >
          <Input.TextArea dir="ltr" autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>
        <Form.Item
          name="client_cert_pem"
          label={t('siem.field.client_cert_pem')}
          extra={editing?.has_client_cert ? t('siem.field.set_keep') : undefined}
        >
          <Input.TextArea dir="ltr" autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>
        <Form.Item name="client_key_pem" label={t('siem.field.client_key_pem')}>
          <Input.TextArea dir="ltr" autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>
      </Form>
    </EditDrawer>
  );
}

/**
 * Admin › Audit › Security monitoring (REQ-AUD-011, WP-057 S5a, template A): where audit and
 * sign-in entries stream, how each destination is doing, and its actions. `audit.manage` only.
 */
export function SiemTab() {
  const t = useLabel();
  const listFormat = useListFormat();
  const { message } = App.useApp();
  const { relative, format } = useDateTime();
  const destinations = useSiemDestinations();
  const rotate = useRotateSiemSecret();
  const test = useTestSiemDestination();
  const remove = useRemoveSiemDestination();
  const change = useChangeSiemDestination();
  const [drawer, setDrawer] = useState<{ open: boolean; editing: SiemDestination | null }>({
    open: false,
    editing: null,
  });
  const [secret, setSecret] = useState<string | null>(null);
  const rows = destinations.data ?? [];
  const problem = useFormProblem();
  const failed = (error: unknown) => {
    problem.show(error);
  };
  return (
    <Flex vertical gap={16} data-testid="siem-tab">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t('siem.intro')}
      </Typography.Paragraph>
      <FormProblem problem={problem} />
      <Flex justify="end">
        <WriteButton
          type="primary"
          onClick={() => {
            setDrawer({ open: true, editing: null });
          }}
          data-testid="siem-add"
        >
          {t('siem.add')}
        </WriteButton>
      </Flex>
      <Table<SiemDestination>
        rowKey="id"
        size="small"
        loading={destinations.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyText>{t('siem.empty')}</EmptyText> }}
        columns={[
          {
            key: 'name',
            title: t('siem.column.name'),
            render: (_, row) => (
              <Flex vertical>
                <Typography.Text strong>{row.name}</Typography.Text>
                <Typography.Text type="secondary" dir="ltr">
                  {row.kind === 'syslog' ? `${row.host ?? ''}:${String(row.port ?? '')}` : row.url}
                </Typography.Text>
              </Flex>
            ),
          },
          {
            key: 'kind',
            title: t('siem.column.kind'),
            render: (_, row) => (
              <Flex gap={4} wrap align="center">
                <span>
                  {`${t(`siem_destination_kind.${row.kind}`)} · ${t(`siem_format.${row.format}`)}`}
                </span>
                {row.transport !== 'tls' && (
                  <span data-testid={`siem-plaintext-${row.name}`}>
                    <ToneTag tone="warning">{t(`siem_transport.${row.transport}`)}</ToneTag>
                  </span>
                )}
              </Flex>
            ),
          },
          {
            key: 'streams',
            title: t('siem.column.streams'),
            render: (_, row) => listFormat(row.streams.map((s) => t(`siem_stream.${s}`))),
          },
          {
            key: 'health',
            title: t('siem.column.health'),
            render: (_, row) => {
              if (!row.enabled) return <ToneTag tone="default">{t('siem.health.off')}</ToneTag>;
              if (row.health.last_error_code !== null && row.health.failing_since !== null) {
                return (
                  <Flex vertical>
                    <ToneTag tone="error">{t(`siem_error.${row.health.last_error_code}`)}</ToneTag>
                    <Typography.Text type="secondary">
                      {t('siem.health.failing_since', { time: relative(row.health.failing_since) })}
                    </Typography.Text>
                  </Flex>
                );
              }
              return (
                <Flex vertical>
                  <ToneTag tone="success">
                    {/* UDP never confirms delivery (D-181): only that it was sent. */}
                    {t(row.transport === 'udp' ? 'siem.health.sent_unconfirmed' : 'siem.health.ok')}
                  </ToneTag>
                  <Typography.Text type="secondary">
                    {row.health.behind > 0
                      ? t('siem.health.behind', { n: row.health.behind })
                      : row.health.last_success_at
                        ? t('siem.health.last', { time: format(row.health.last_success_at) })
                        : t('siem.health.waiting')}
                  </Typography.Text>
                </Flex>
              );
            },
          },
          {
            key: 'actions',
            title: t('siem.column.actions'),
            render: (_, row) => (
              <Space wrap>
                <Button
                  size="small"
                  onClick={() => {
                    setDrawer({ open: true, editing: row });
                  }}
                >
                  {t('siem.action.edit')}
                </Button>
                <Button
                  size="small"
                  loading={test.isPending && test.variables.id === row.id}
                  onClick={() => {
                    problem.clear();
                    test.mutate(
                      { id: row.id },
                      {
                        onSuccess: (result) => {
                          if (result.result === 'delivered')
                            void message.success(t('siem.test.delivered'));
                          else
                            void message.error(
                              t(`siem_error.${result.error_code ?? 'unreachable'}`),
                            );
                        },
                        onError: failed,
                      },
                    );
                  }}
                  data-testid="siem-test"
                >
                  {t('siem.action.test')}
                </Button>
                <Switch
                  size="small"
                  checked={row.enabled}
                  aria-label={t('siem.field.enabled')}
                  onChange={(enabled) => {
                    change.mutate(
                      {
                        id: row.id,
                        version: row.version,
                        body: {
                          name: row.name,
                          kind: row.kind,
                          format: row.format,
                          host: row.host,
                          port: row.port,
                          url: row.url,
                          streams: row.streams,
                          enabled,
                          // Unchanged: switching it on or off never changes how it is sent.
                          transport: row.transport,
                          udp_max_bytes: row.udp_max_bytes,
                        },
                      },
                      { onError: failed },
                    );
                  }}
                />
                {row.kind === 'webhook' && (
                  <Button
                    size="small"
                    onClick={() => {
                      rotate.mutate(
                        { id: row.id, version: row.version, finish: row.rotating },
                        {
                          onSuccess: (made) => {
                            if (made.secret) setSecret(made.secret);
                            rotate.reset();
                          },
                          onError: failed,
                        },
                      );
                    }}
                  >
                    {row.rotating ? t('siem.action.finish_rotation') : t('siem.action.rotate')}
                  </Button>
                )}
                <Popconfirm
                  title={t('siem.remove.confirm', { name: row.name })}
                  okText={t('siem.action.remove')}
                  okButtonProps={{ danger: true }}
                  cancelText={t('actions.cancel')}
                  onConfirm={() => {
                    remove.mutate({ id: row.id }, { onError: failed });
                  }}
                >
                  <Button size="small" danger>
                    {t('siem.action.remove')}
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      {rows.some((row) => row.rotating) && (
        <Alert type="info" showIcon message={t('siem.rotating_notice')} />
      )}
      <DestinationDrawer
        open={drawer.open}
        editing={drawer.editing}
        onClose={() => {
          setDrawer({ open: false, editing: null });
        }}
        onSecret={setSecret}
      />
      {secret !== null && (
        <SecretDialog
          secret={secret}
          onClose={() => {
            setSecret(null);
          }}
        />
      )}
    </Flex>
  );
}
