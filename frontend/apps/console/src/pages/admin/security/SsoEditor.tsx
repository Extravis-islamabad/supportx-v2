import { Collapse, Drawer, Flex, Input, Segmented, Select, Space, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useCreateSso,
  useUpdateSso,
  type SsoInput,
  type SsoProvider,
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

import { ssoView, useSsoFieldName } from './conflict';
import { FieldNote } from './FieldNote';

type Preset = SsoInput['preset'];
const PRESETS: Preset[] = ['entra', 'okta', 'google', 'oidc', 'saml'];
const OIDC_MAPPING = { email: 'email', first_name: 'given_name', last_name: 'family_name' };
const SAML_MAPPING = {
  email: 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress',
  first_name: 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname',
  last_name: 'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname',
};
const GOOGLE_ISSUER = 'https://accounts.google.com';
const DOMAIN = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$/;
const MAPPED = ['email', 'first_name', 'last_name', 'department', 'site'] as const;

type Mapping = Record<(typeof MAPPED)[number], string>;

interface Form {
  preset: Preset;
  display_name: string;
  domains: string[];
  email_redirect: boolean;
  issuer: string;
  client_id: string;
  client_secret: string;
  scopes: string;
  metadata: string;
  metadata_url: string;
  sso_url: string;
  certificate: string;
  mapping: Mapping;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function formFrom(saved: SsoProvider | null, preset: Preset): Form {
  const settings = saved?.settings ?? {};
  const mapping = (settings.mapping ?? {}) as Partial<Mapping>;
  const defaults = preset === 'saml' ? SAML_MAPPING : OIDC_MAPPING;
  return {
    preset,
    display_name: saved?.display_name ?? '',
    domains: saved?.domains ?? [],
    email_redirect: saved?.email_redirect ?? false,
    issuer: text(settings.issuer) || (preset === 'google' ? GOOGLE_ISSUER : ''),
    client_id: text(settings.client_id),
    client_secret: '',
    scopes: text(settings.scopes) || 'openid email profile',
    metadata: '',
    metadata_url: '',
    sso_url: '',
    certificate: '',
    mapping: {
      email: mapping.email ?? defaults.email,
      first_name: mapping.first_name ?? defaults.first_name,
      last_name: mapping.last_name ?? defaults.last_name,
      department: mapping.department ?? '',
      site: mapping.site ?? '',
    },
  };
}

function isUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:';
  } catch {
    return false;
  }
}

/** Problems with what is typed, at once; the server checks the connection on save. */
function typedProblems(form: Form, editing: boolean): Record<string, string> {
  const found: Record<string, string> = {};
  const bad = form.domains.find((d) => !DOMAIN.test(d.trim().toLowerCase()));
  if (bad !== undefined) found.domains = `errors.field.sso_domain_invalid|${bad}`;
  if (form.preset === 'saml') return found;
  if (form.issuer !== '' && !isUrl(form.issuer)) found.issuer = 'errors.field.sso_url_invalid';
  if (!editing && form.client_secret === '' && form.client_id !== '') {
    found.client_secret = 'errors.field.sso_client_secret_required';
  }
  return found;
}

/**
 * Add or change a single sign-on set-up (REQ-SEC-007, REQ-SEC-008): Microsoft Entra ID, Okta,
 * Google, any OpenID Connect provider, or SAML 2.0. The client secret is write-only; SAML
 * metadata is read by the sign-in service. Saved in draft: test it, then switch it on.
 */
export function SsoEditor({
  open,
  provider: opened,
  latest,
  onClose,
}: {
  open: boolean;
  /** The set-up as it was when the editor opened (null: a new one). */
  provider: SsoProvider | null;
  /** The same set-up as it is now (live), for the conflict dialog. */
  latest?: SsoProvider;
  onClose: (saved: SsoProvider | null) => void;
}) {
  const t = useLabel();
  const create = useCreateSso();
  const update = useUpdateSso();
  // The version this form is based on: "Reload" and "Keep my changes" move it on (BUG-05).
  const [provider, setProvider] = useState(opened);
  const conflict = useConflict();
  const ssoField = useSsoFieldName();
  const editing = provider !== null;
  const [form, setForm] = useState<Form>(() => formFrom(provider, provider?.preset ?? 'entra'));
  const [refused, setRefused] = useState<Record<string, string>>({});
  // A refusal with no field to point at is shown at the top of the editor (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const [key] = useState(() => crypto.randomUUID());
  const saml = form.preset === 'saml';
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
    form.display_name.trim() !== '' &&
    form.domains.length > 0 &&
    (saml
      ? form.metadata !== '' || form.metadata_url !== '' || form.sso_url !== '' || editing
      : form.issuer !== '' && form.client_id !== '');

  const body = (): SsoInput => {
    const mapping = {
      ...form.mapping,
      department: form.mapping.department || null,
      site: form.mapping.site || null,
    };
    const shared = {
      preset: form.preset,
      display_name: form.display_name.trim(),
      domains: form.domains.map((d) => d.trim().toLowerCase()),
      email_redirect: form.email_redirect,
      mapping,
    };
    if (!saml) {
      return {
        ...shared,
        issuer: form.issuer.trim(),
        client_id: form.client_id.trim(),
        client_secret: form.client_secret === '' ? null : form.client_secret,
        scopes: form.scopes.trim(),
      };
    }
    return {
      ...shared,
      scopes: form.scopes,
      metadata: form.metadata || null,
      metadata_url: form.metadata_url.trim() || null,
      sso_url: form.sso_url.trim() || null,
      certificate: form.certificate.trim() || null,
    };
  };

  const onError = (error: unknown) => {
    // Another admin saved this set-up first: the shared dialog says who, when and what.
    if (conflict.take(error)) return;
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      setRefused(
        Object.fromEntries(
          error.fieldErrors.map((f) => {
            const domain = f.params?.domain;
            return [
              f.field,
              typeof domain === 'string' ? `${f.message_key}|${domain}` : f.message_key,
            ];
          }),
        ),
      );
      return;
    }
    problem.show(error);
  };
  const submit = (version = provider?.version ?? 0) => {
    problem.clear();
    if (provider === null) {
      create.mutate(
        { body: body(), key },
        {
          onSuccess: (saved) => {
            onClose(saved);
          },
          onError,
        },
      );
    } else {
      update.mutate(
        { id: provider.id, body: body(), version },
        {
          onSuccess: (saved) => {
            onClose(saved);
          },
          onError,
        },
      );
    }
  };

  const field = (name: keyof Form, labelKey: string, input: React.ReactNode, hintKey?: string) => (
    <FieldNote id={`sso-${name}`} message={message(name)}>
      <label htmlFor={`sso-${name}`}>{t(labelKey)}</label>
      {input}
      {hintKey !== undefined && <Typography.Text type="secondary">{t(hintKey)}</Typography.Text>}
    </FieldNote>
  );
  const textInput = (name: 'issuer' | 'client_id' | 'scopes' | 'metadata_url' | 'sso_url') => (
    <Input
      id={`sso-${name}`}
      value={form[name]}
      status={message(name) === null ? undefined : 'error'}
      aria-describedby={`sso-${name}-problem`}
      onChange={(event) => {
        set({ [name]: event.target.value }, name);
      }}
      data-testid={`sso-${name}`}
    />
  );

  return (
    <Drawer
      open={open}
      width={560}
      title={t(editing ? 'security.sso.edit_title' : 'security.sso.add_title')}
      onClose={() => {
        problem.clear();
        onClose(null);
      }}
      destroyOnHidden
      data-testid="sso-editor"
      extra={
        <WriteButton
          type="primary"
          loading={create.isPending || update.isPending}
          disabled={!required || Object.keys(typed).length > 0}
          onClick={() => {
            submit();
          }}
          data-testid="sso-save"
        >
          {t('actions.save')}
        </WriteButton>
      }
    >
      <FormProblem problem={problem} />
      <Flex vertical gap={16}>
        <Segmented
          value={form.preset}
          options={PRESETS.map((preset) => ({
            value: preset,
            label: t(`sso_preset.${preset}`),
            // A set-up keeps its protocol (SAML or OpenID Connect).
            disabled: editing && (preset === 'saml') !== (provider.preset === 'saml'),
          }))}
          onChange={(preset) => {
            const next = formFrom(provider, preset);
            setForm({ ...next, display_name: form.display_name, domains: form.domains });
          }}
          data-testid="sso-preset"
        />
        <Typography.Text type="secondary">
          {t(`security.sso.preset_hint.${form.preset}`)}
        </Typography.Text>
        {field(
          'display_name',
          'security.sso.display_name',
          <Input
            id="sso-display_name"
            value={form.display_name}
            count={lengthLimit(80)}
            status={message('display_name') === null ? undefined : 'error'}
            onChange={(event) => {
              set({ display_name: event.target.value }, 'display_name');
            }}
            data-testid="sso-display_name"
          />,
        )}
        {field(
          'domains',
          'security.sso.domains',
          <Select
            id="sso-domains"
            mode="tags"
            open={false}
            tokenSeparators={[',', ' ', ';']}
            value={form.domains}
            status={message('domains') === null ? undefined : 'error'}
            onChange={(domains: string[]) => {
              set({ domains }, 'domains');
            }}
            aria-describedby="sso-domains-problem"
            data-testid="sso-domains"
          />,
          'security.sso.domains_hint',
        )}
        {saml ? (
          <>
            {field(
              'metadata',
              'security.sso.metadata',
              <input
                id="sso-metadata"
                type="file"
                accept=".xml,application/xml,text/xml"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file !== undefined) {
                    void file.text().then((metadata) => {
                      set({ metadata }, 'metadata');
                    });
                  }
                }}
                data-testid="sso-metadata"
              />,
              editing ? 'security.sso.metadata_kept' : 'security.sso.metadata_hint',
            )}
            {field('metadata_url', 'security.sso.metadata_url', textInput('metadata_url'))}
            <Collapse
              items={[
                {
                  key: 'manual',
                  label: t('security.sso.by_hand'),
                  children: (
                    <Flex vertical gap={12}>
                      {field('sso_url', 'security.sso.sso_url', textInput('sso_url'))}
                      {field(
                        'certificate',
                        'security.sso.certificate',
                        <Input.TextArea
                          id="sso-certificate"
                          rows={4}
                          value={form.certificate}
                          onChange={(event) => {
                            set({ certificate: event.target.value }, 'certificate');
                          }}
                          style={{ fontFamily: 'monospace' }}
                          data-testid="sso-certificate"
                        />,
                      )}
                    </Flex>
                  ),
                },
              ]}
            />
          </>
        ) : (
          <>
            {field(
              'issuer',
              'security.sso.issuer',
              textInput('issuer'),
              `security.sso.issuer_hint.${form.preset}`,
            )}
            {field('client_id', 'security.sso.client_id', textInput('client_id'))}
            {field(
              'client_secret',
              'security.sso.client_secret',
              <Input.Password
                id="sso-client_secret"
                value={form.client_secret}
                placeholder={editing ? t('security.sso.secret_kept') : undefined}
                autoComplete="new-password"
                status={message('client_secret') === null ? undefined : 'error'}
                onChange={(event) => {
                  set({ client_secret: event.target.value }, 'client_secret');
                }}
                data-testid="sso-client_secret"
              />,
              'security.sso.secret_hint',
            )}
            {field('scopes', 'security.sso.scopes', textInput('scopes'))}
          </>
        )}
        <Collapse
          items={[
            {
              key: 'mapping',
              label: t('security.sso.mapping'),
              children: (
                <Flex vertical gap={12}>
                  <Typography.Text type="secondary">
                    {t(saml ? 'security.sso.mapping_hint_saml' : 'security.sso.mapping_hint_oidc')}
                  </Typography.Text>
                  {MAPPED.map((name) => (
                    <Flex key={name} vertical gap={4}>
                      <label htmlFor={`sso-map-${name}`}>{t(`security.sso.map.${name}`)}</label>
                      <Input
                        id={`sso-map-${name}`}
                        value={form.mapping[name]}
                        onChange={(event) => {
                          set({ mapping: { ...form.mapping, [name]: event.target.value } });
                        }}
                        data-testid={`sso-map-${name}`}
                      />
                    </Flex>
                  ))}
                </Flex>
              ),
            },
          ]}
        />
        <Flex vertical gap={4}>
          <Space>
            <Switch
              checked={form.email_redirect}
              onChange={(on) => {
                set({ email_redirect: on });
              }}
              aria-labelledby="sso-email-redirect-label"
              data-testid="sso-email_redirect"
            />
            <Typography.Text id="sso-email-redirect-label">
              {t('security.sso.email_redirect')}
            </Typography.Text>
          </Space>
          <Typography.Text type="secondary">
            {t('security.sso.email_redirect_hint')}
          </Typography.Text>
        </Flex>
      </Flex>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={ssoField}
        opened={ssoView(provider)}
        latest={ssoView(latest)}
        onReload={() => {
          conflict.clear();
          if (latest === undefined) return;
          setProvider(latest);
          setForm(formFrom(latest, latest.preset));
          setRefused({});
        }}
        onKeepMine={() => {
          conflict.clear();
          if (latest !== undefined) setProvider(latest);
          submit(conflict.latestVersion ?? latest?.version);
        }}
      />
    </Drawer>
  );
}
