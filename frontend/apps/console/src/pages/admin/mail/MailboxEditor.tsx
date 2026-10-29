import { Drawer, Flex, Input, InputNumber, Select, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useCreateMailbox,
  useUpdateMailbox,
  type Mailbox,
  type MailboxChange,
} from '@supportx/api-client';
import {
  ConflictDialog,
  FormProblem,
  lengthLimit,
  markHandled,
  useConflict,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { FieldNote } from '../security/FieldNote';
import { mailboxView, useMailboxFieldName } from './conflict';

type Security = Mailbox['security'];
type AfterFetch = Mailbox['after_fetch'];
type Creates = Mailbox['creates'];
type UnknownSenders = Mailbox['unknown_senders'];
const SECURITY: Security[] = ['tls', 'starttls', 'none'];
const AFTER_FETCH: AfterFetch[] = ['mark_read', 'move', 'delete'];
const CREATES: Creates[] = ['incident', 'nothing'];
const UNKNOWN: UnknownSenders[] = ['create_allowed_domains', 'create', 'reject'];
const PORTS: Record<Security, number> = { tls: 993, starttls: 143, none: 143 };
const DOMAIN = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;

interface Form {
  address: string;
  display_name: string;
  host: string;
  port: number;
  security: Security;
  allow_plain: boolean;
  username: string;
  password: string;
  folder: string;
  after_fetch: AfterFetch;
  move_to: string;
  creates: Creates;
  unknown_senders: UnknownSenders;
  allowed_domains: string[];
  enabled: boolean;
}

function formFrom(saved: Mailbox | null): Form {
  return {
    address: saved?.address ?? '',
    display_name: saved?.display_name ?? '',
    host: saved?.host ?? '',
    port: saved?.port ?? 993,
    security: saved?.security ?? 'tls',
    allow_plain: saved?.allow_plain ?? false,
    username: saved?.username ?? '',
    password: '',
    folder: saved?.folder ?? 'INBOX',
    after_fetch: saved?.after_fetch ?? 'mark_read',
    move_to: saved?.move_to ?? '',
    creates: saved?.creates ?? 'incident',
    unknown_senders: saved?.unknown_senders ?? 'create_allowed_domains',
    allowed_domains: saved?.allowed_domains ?? [],
    enabled: saved?.enabled ?? true,
  };
}

/** What is wrong with what is typed, at once (the server checks again on save). */
function typedProblems(form: Form, editing: boolean): Record<string, string> {
  const found: Record<string, string> = {};
  if (!editing && form.address !== '' && !/^[^@\s]+@[^@\s]+$/.test(form.address.trim())) {
    found.address = 'errors.field.mailbox_address_invalid';
  }
  if (form.security === 'none' && !form.allow_plain) {
    found.security = 'errors.field.plain_connection_refused';
  }
  if (form.after_fetch === 'move' && form.move_to.trim() === '') {
    found.move_to = 'errors.field.required';
  }
  const bad = form.allowed_domains.find((d) => !DOMAIN.test(d.trim().toLowerCase()));
  if (bad !== undefined) found.allowed_domains = `errors.field.sso_domain_invalid|${bad}`;
  return found;
}

/**
 * Add or change a support mailbox (WP-024; REQ-INT-050, REQ-INT-051, REQ-INC-027): where to read
 * mail, what it becomes, and what happens to mail from people SupportX does not know. The password
 * is write-only. A connection without encryption needs an explicit, audited choice.
 */
export function MailboxEditor({
  mailbox: opened,
  latest,
  onClose,
}: {
  /** The mailbox as it was when the editor opened (null: a new one). */
  mailbox: Mailbox | null;
  /** The same mailbox as it is now (live), for the conflict dialog. */
  latest?: Mailbox;
  onClose: () => void;
}) {
  const t = useLabel();
  const create = useCreateMailbox();
  const update = useUpdateMailbox();
  const [mailbox, setMailbox] = useState(opened);
  const conflict = useConflict();
  const fieldName = useMailboxFieldName();
  const editing = mailbox !== null;
  const [form, setForm] = useState<Form>(() => formFrom(mailbox));
  const [refused, setRefused] = useState<Record<string, string>>({});
  const problem = useFormProblem();
  const [key] = useState(() => crypto.randomUUID());
  const typed = typedProblems(form, editing);
  const message = (field: string): string | null => {
    const found = typed[field] ?? refused[field];
    if (found === undefined) return null;
    const [labelKey, domain] = found.split('|');
    return t(labelKey ?? found, domain === undefined ? {} : { domain });
  };
  const set = (change: Partial<Form>, ...fields: string[]) => {
    setForm({ ...form, ...change });
    setRefused((current) =>
      Object.fromEntries(Object.entries(current).filter(([f]) => !fields.includes(f))),
    );
  };
  const required =
    form.host.trim() !== '' &&
    form.username.trim() !== '' &&
    form.folder.trim() !== '' &&
    (editing || (form.address.trim() !== '' && form.password !== ''));

  const body = (): MailboxChange => ({
    display_name: form.display_name.trim() || null,
    host: form.host.trim(),
    port: form.port,
    security: form.security,
    allow_plain: form.allow_plain,
    username: form.username.trim(),
    folder: form.folder.trim(),
    after_fetch: form.after_fetch,
    move_to: form.after_fetch === 'move' ? form.move_to.trim() : null,
    creates: form.creates,
    unknown_senders: form.unknown_senders,
    allowed_domains: form.allowed_domains.map((d) => d.trim().toLowerCase()),
    enabled: form.enabled,
    ...(form.password === '' ? {} : { password: form.password }),
  });

  const onError = (error: unknown) => {
    // Another admin saved this mailbox first: the shared dialog says what changed.
    if (conflict.take(error)) return;
    // The address another mailbox reads: said at the address, not as a dialog.
    if (error instanceof ApiError && error.code === 'mailbox_address_taken') {
      markHandled(error);
      setRefused({ address: 'errors.mailbox_address_taken' });
      return;
    }
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
  const submit = (version = mailbox?.version ?? 0) => {
    problem.clear();
    if (mailbox === null) {
      create.mutate(
        {
          body: {
            ...body(),
            address: form.address.trim(),
            host: form.host.trim(),
            port: form.port,
            username: form.username.trim(),
            password: form.password,
          },
          key,
        },
        { onSuccess: onClose, onError },
      );
    } else {
      update.mutate({ id: mailbox.id, body: body(), version }, { onSuccess: onClose, onError });
    }
  };

  const field = (name: keyof Form, labelKey: string, input: React.ReactNode, hintKey?: string) => (
    <FieldNote id={`mailbox-${name}`} message={message(name)}>
      <label htmlFor={`mailbox-${name}`}>{t(labelKey)}</label>
      {input}
      {hintKey !== undefined && <Typography.Text type="secondary">{t(hintKey)}</Typography.Text>}
    </FieldNote>
  );
  const status = (name: string) => (message(name) === null ? undefined : 'error');
  const text = (name: 'address' | 'host' | 'username' | 'folder' | 'move_to', max = 255) => (
    <Input
      id={`mailbox-${name}`}
      value={form[name]}
      count={lengthLimit(max)}
      status={status(name)}
      aria-describedby={`mailbox-${name}-problem`}
      onChange={(event) => {
        set({ [name]: event.target.value }, name);
      }}
      data-testid={`mailbox-${name}`}
    />
  );
  const choice = (name: keyof Form, values: readonly string[], labelPrefix: string) => (
    <Select<string>
      id={`mailbox-${name}`}
      value={String(form[name])}
      status={status(name)}
      aria-describedby={`mailbox-${name}-problem`}
      options={values.map((value) => ({ value, label: t(`${labelPrefix}.${value}`) }))}
      onChange={(value) => {
        const change: Partial<Form> = { [name]: value };
        // A new mailbox takes the usual port of the encryption chosen.
        if (name === 'security' && !editing) change.port = PORTS[value as Security];
        set(change, name);
      }}
      data-testid={`mailbox-${name}`}
    />
  );

  return (
    <Drawer
      open
      width={560}
      title={t(editing ? 'mail.edit_title' : 'mail.add_title')}
      onClose={() => {
        problem.clear();
        onClose();
      }}
      destroyOnHidden
      data-testid="mailbox-editor"
      extra={
        <WriteButton
          type="primary"
          loading={create.isPending || update.isPending}
          disabled={!required || Object.keys(typed).length > 0}
          onClick={() => {
            submit();
          }}
          data-testid="mailbox-save"
        >
          {t('actions.save')}
        </WriteButton>
      }
    >
      <FormProblem problem={problem} />
      <Flex vertical gap={16}>
        {editing ? (
          <Typography.Text strong data-testid="mailbox-address-shown">
            {mailbox.address}
          </Typography.Text>
        ) : (
          field('address', 'mail.field.address', text('address', 320))
        )}
        {field(
          'display_name',
          'mail.field.display_name',
          <Input
            id="mailbox-display_name"
            value={form.display_name}
            count={lengthLimit(120)}
            onChange={(event) => {
              set({ display_name: event.target.value }, 'display_name');
            }}
            data-testid="mailbox-display_name"
          />,
        )}
        <Typography.Title level={5} style={{ margin: 0 }}>
          {t('mail.section.connection')}
        </Typography.Title>
        {field('host', 'mail.field.host', text('host'))}
        <Flex gap={12} wrap>
          {field(
            'security',
            'mail.field.security',
            choice('security', SECURITY, 'mailbox_security'),
          )}
          {field(
            'port',
            'mail.field.port',
            <InputNumber
              id="mailbox-port"
              min={1}
              max={65535}
              value={form.port}
              onChange={(port) => {
                set({ port: port ?? PORTS[form.security] }, 'port');
              }}
              data-testid="mailbox-port"
            />,
          )}
        </Flex>
        {form.security === 'none' &&
          field(
            'allow_plain',
            'mail.field.allow_plain',
            <Switch
              id="mailbox-allow_plain"
              checked={form.allow_plain}
              onChange={(allow_plain) => {
                set({ allow_plain }, 'allow_plain', 'security');
              }}
              data-testid="mailbox-allow_plain"
            />,
            'mail.field.allow_plain_hint',
          )}
        {field('username', 'mail.field.username', text('username', 320))}
        {field(
          'password',
          'mail.field.password',
          <Input.Password
            id="mailbox-password"
            value={form.password}
            autoComplete="new-password"
            status={status('password')}
            onChange={(event) => {
              set({ password: event.target.value }, 'password');
            }}
            data-testid="mailbox-password"
          />,
          editing ? 'mail.field.password_keep' : undefined,
        )}
        {field('folder', 'mail.field.folder', text('folder'))}
        {field(
          'after_fetch',
          'mail.field.after_fetch',
          choice('after_fetch', AFTER_FETCH, 'mailbox_after_fetch'),
          'mail.field.after_fetch_hint',
        )}
        {form.after_fetch === 'move' && field('move_to', 'mail.field.move_to', text('move_to'))}
        <Typography.Title level={5} style={{ margin: 0 }}>
          {t('mail.section.mail')}
        </Typography.Title>
        {field('creates', 'mail.field.creates', choice('creates', CREATES, 'mailbox_creates'))}
        {field(
          'unknown_senders',
          'mail.field.unknown_senders',
          choice('unknown_senders', UNKNOWN, 'mailbox_unknown_senders'),
        )}
        {form.unknown_senders === 'create_allowed_domains' &&
          field(
            'allowed_domains',
            'mail.field.allowed_domains',
            <Select
              id="mailbox-allowed_domains"
              mode="tags"
              open={false}
              tokenSeparators={[',', ' ', ';']}
              value={form.allowed_domains}
              status={status('allowed_domains')}
              aria-describedby="mailbox-allowed_domains-problem"
              onChange={(allowed_domains: string[]) => {
                set({ allowed_domains }, 'allowed_domains');
              }}
              data-testid="mailbox-allowed_domains"
            />,
            'mail.field.allowed_domains_hint',
          )}
        {field(
          'enabled',
          'mail.field.enabled',
          <Switch
            id="mailbox-enabled"
            checked={form.enabled}
            onChange={(enabled) => {
              set({ enabled }, 'enabled');
            }}
            data-testid="mailbox-enabled"
          />,
        )}
      </Flex>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={fieldName}
        opened={mailboxView(mailbox)}
        latest={mailboxView(latest)}
        onReload={() => {
          conflict.clear();
          if (latest === undefined) return;
          setMailbox(latest);
          setForm(formFrom(latest));
          setRefused({});
        }}
        onKeepMine={() => {
          conflict.clear();
          if (latest !== undefined) setMailbox(latest);
          submit(conflict.latestVersion ?? latest?.version);
        }}
      />
    </Drawer>
  );
}
