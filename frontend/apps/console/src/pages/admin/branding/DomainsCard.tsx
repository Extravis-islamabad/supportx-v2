import { App, Card, Flex, Input, List, Modal, Space, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  ApiError,
  queryKeys,
  useAddDomain,
  useDomains,
  useRemoveDomain,
  useUploadCertificate,
  useVerifyDomain,
  type CustomDomain,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  describeError,
  FormProblem,
  markHandled,
  reportError,
  ToneTag,
  useConflict,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { domainProblem, fieldProblems, pemProblem } from './checks';
import { FieldProblem } from './FieldProblem';

const DOMAINS_CHANGED = 'organization.domains_changed';
const STATUS_TONE = { pending: 'default', verified: 'success', failed: 'error' } as const;
/** Refusals of a domain that are about the host typed, said at the field (QA BUG-02). */
const HOST_CONFLICTS = new Set(['domain_taken', 'domain_limit']);
type Translate = ReturnType<typeof useLabel>;

/** The server's reason a field was refused, translated; null when the error is not about it. */
function refusalAt(t: Translate, error: unknown, field: string): string | null {
  const found = fieldProblems(error)[field];
  return found === undefined ? null : found.map((p) => t(p.key, p.params)).join(' ');
}

/** What a person sees of a domain, for the conflict dialog (QA WP-029 BUG-05). */
const domainView = (domain: CustomDomain | null | undefined) =>
  domain == null
    ? undefined
    : {
        status: domain.status,
        tls_status: domain.tls_status,
        certificate_not_after: domain.certificate_not_after,
      };
const domainPart = (t: Translate, field: string) =>
  t(field === 'status' ? 'domains.status' : 'domains.tls');

function CertificateDialog({
  domain: opened,
  latest,
  onClose,
}: {
  /** The domain as it was when the dialog opened. */
  domain: CustomDomain | null;
  /** The same domain as it is now (live), for the conflict dialog. */
  latest: CustomDomain | undefined;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const upload = useUploadCertificate();
  const [certificate, setCertificate] = useState('');
  const [privateKey, setPrivateKey] = useState('');
  // The server's refusal stays until the field it is about changes.
  const [refused, setRefused] = useState<unknown>(null);
  // A refusal with no field to point at is shown in the dialog too (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // A domain another admin changed first (409): the shared dialog (BUG-05).
  const conflict = useConflict();
  const [domain, setDomain] = useState(opened);
  if (opened?.id !== domain?.id) setDomain(opened);
  const send = (version = domain?.version) => {
    if (domain === null || version === undefined) return;
    problem.clear();
    upload.mutate(
      { id: domain.id, version, certificate, privateKey },
      {
        onSuccess: () => {
          void message.success(t('domains.certificate_saved'));
          setCertificate('');
          setPrivateKey('');
          setRefused(null);
          onClose();
        },
        // What is wrong with the certificate is said in the dialog, which stays open.
        onError: (error) => {
          if (conflict.take(error)) return;
          if (Object.keys(fieldProblems(error)).length === 0) problem.show(error);
          else markHandled(error);
          setRefused(error);
        },
      },
    );
  };
  const typed = {
    certificate: pemProblem('certificate', certificate),
    private_key: pemProblem('private_key', privateKey),
  };
  const problemOf = (field: 'certificate' | 'private_key') => {
    const code = typed[field];
    return code === null ? refusalAt(t, refused, field) : t(`errors.field.${code}`);
  };
  return (
    <Modal
      open={domain !== null}
      title={t('domains.certificate_title', { host: domain?.host ?? '' })}
      okText={t('domains.certificate_save')}
      cancelText={t('actions.cancel')}
      confirmLoading={upload.isPending}
      okButtonProps={{
        disabled:
          certificate === '' ||
          privateKey === '' ||
          typed.certificate !== null ||
          typed.private_key !== null,
      }}
      destroyOnHidden
      onCancel={() => {
        setRefused(null);
        problem.clear();
        onClose();
      }}
      onOk={() => {
        send();
      }}
    >
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => domainPart(t, field)}
        opened={domainView(domain)}
        latest={domainView(latest)}
        onReload={() => {
          conflict.clear();
          setCertificate('');
          setPrivateKey('');
          if (latest !== undefined) setDomain(latest);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (latest !== undefined) setDomain(latest);
          send(conflict.latestVersion ?? latest?.version);
        }}
      />
      <Flex vertical gap={12}>
        <FormProblem problem={problem} />
        <Typography.Paragraph type="secondary">
          {t('domains.certificate_hint')}
        </Typography.Paragraph>
        <FieldProblem
          testId="domain-certificate-field"
          id="domain-certificate-problem"
          message={problemOf('certificate')}
        >
          <label htmlFor="domain-certificate">{t('domains.certificate')}</label>
          <Input.TextArea
            id="domain-certificate"
            rows={5}
            value={certificate}
            status={problemOf('certificate') === null ? undefined : 'error'}
            aria-describedby="domain-certificate-problem"
            onChange={(event) => {
              setCertificate(event.target.value);
              setRefused(null);
            }}
            style={{ fontFamily: 'monospace' }}
            data-testid="domain-certificate"
          />
        </FieldProblem>
        <FieldProblem
          testId="domain-private-key-field"
          id="domain-private-key-problem"
          message={problemOf('private_key')}
        >
          <label htmlFor="domain-private-key">{t('domains.private_key')}</label>
          <Input.TextArea
            id="domain-private-key"
            rows={5}
            value={privateKey}
            status={problemOf('private_key') === null ? undefined : 'error'}
            aria-describedby="domain-private-key-problem"
            onChange={(event) => {
              setPrivateKey(event.target.value);
              setRefused(null);
            }}
            style={{ fontFamily: 'monospace' }}
            data-testid="domain-private-key"
          />
        </FieldProblem>
      </Flex>
    </Modal>
  );
}

/**
 * The tenant's addresses (WP-017, REQ-PRT-016 AC3, REQ-SEC-004): its subdomain when the
 * installation has them, and custom domains: add, point the DNS record, check, give a certificate
 * (automatic, or the tenant's own on a single-server installation), remove. Changes made elsewhere
 * show without a reload.
 */
export function DomainsCard() {
  const t = useLabel();
  const dates = useDateTime();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const domains = useDomains();
  const add = useAddDomain();
  const verify = useVerifyDomain();
  const remove = useRemoveDomain();
  const [host, setHost] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [certificateFor, setCertificateFor] = useState<CustomDomain | null>(null);
  // Why the typed host cannot be added: checked as it is typed, or the server's last refusal.
  const [hostRefusal, setHostRefusal] = useState<string | null>(null);
  const typedProblem = domainProblem(host);
  const hostMessage = typedProblem === null ? hostRefusal : t(`errors.field.${typedProblem}`);
  useTenantChannel((event) => {
    if (event.type === DOMAINS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.branding.domains });
    }
  });

  const data = domains.data;
  // A domain another admin changed first (409) while removing it: the shared dialog (BUG-05).
  const conflict = useConflict();
  const [removing, setRemoving] = useState<CustomDomain>();
  const live = data?.items.find((d) => d.id === removing?.id);
  const removeDomain = (domain: CustomDomain, version = domain.version) =>
    remove.mutateAsync({ id: domain.id, version }).catch((error: unknown) => {
      if (conflict.take(error)) setRemoving(domain);
      else reportError(error);
    });
  return (
    <Card title={t('domains.title')} data-testid="branding-domains">
      <Flex vertical gap={12}>
        {data?.subdomain != null && (
          <Typography.Text data-testid="domains-subdomain">
            {t('domains.subdomain')} <Typography.Text code>{data.subdomain}</Typography.Text>
          </Typography.Text>
        )}
        <Typography.Text type="secondary">
          {t('domains.how', { target: data?.point_to ?? '' })}
        </Typography.Text>
        <FieldProblem testId="domains-host-field" id="domains-host-problem" message={hostMessage}>
          <Space.Compact style={{ maxWidth: 480, width: '100%' }}>
            <Input
              value={host}
              placeholder={t('domains.host_example')}
              aria-label={t('domains.host')}
              status={hostMessage === null ? undefined : 'error'}
              aria-invalid={hostMessage !== null}
              aria-describedby="domains-host-problem"
              onChange={(event) => {
                setHost(event.target.value);
                setHostRefusal(null);
              }}
              data-testid="domains-host"
            />
            <WriteButton
              type="primary"
              disabled={host.trim() === '' || typedProblem !== null}
              loading={add.isPending}
              onClick={() => {
                add.mutate(
                  { host: host.trim(), key },
                  {
                    onSuccess: () => {
                      setHost('');
                      setHostRefusal(null);
                      setKey(crypto.randomUUID());
                    },
                    onError: (error) => {
                      // Any refusal is said at the host field, once (QA WP-029 BUG-02).
                      const atField =
                        refusalAt(t, error, 'host') ??
                        (error instanceof ApiError && HOST_CONFLICTS.has(error.code)
                          ? t(error.messageKey, error.params)
                          : error instanceof ApiError && error.isRefusal && !error.isConflict
                            ? describeError(error, t).title
                            : null);
                      if (atField === null) reportError(error);
                      else markHandled(error);
                      setHostRefusal(atField);
                      // A refused key may not be retried with another host.
                      setKey(crypto.randomUUID());
                    },
                  },
                );
              }}
              data-testid="domains-add"
            >
              {t('domains.add')}
            </WriteButton>
          </Space.Compact>
        </FieldProblem>
        <List
          dataSource={data?.items ?? []}
          // Readable in every theme (QA BUG-05: the faint empty style failed contrast in dark).
          locale={{
            emptyText: <Typography.Text type="secondary">{t('domains.none')}</Typography.Text>,
          }}
          renderItem={(domain) => (
            <List.Item
              data-testid={`domain-${domain.host}`}
              actions={[
                <WriteButton
                  key="verify"
                  size="small"
                  loading={verify.isPending && verify.variables === domain.id}
                  onClick={() => {
                    verify.mutate(domain.id, {
                      onSuccess: (checked) =>
                        void message[checked.status === 'verified' ? 'success' : 'warning'](
                          t(
                            checked.status === 'verified'
                              ? 'domains.verified'
                              : `errors.${checked.failure_code ?? 'domain_check_failed'}`,
                          ),
                        ),
                      onError: reportError,
                    });
                  }}
                  data-testid={`domain-verify-${domain.host}`}
                >
                  {t('domains.check')}
                </WriteButton>,
                <WriteButton
                  key="certificate"
                  size="small"
                  onClick={() => {
                    setCertificateFor(domain);
                  }}
                  data-testid={`domain-certificate-${domain.host}`}
                >
                  {t('domains.upload_certificate')}
                </WriteButton>,
                <WriteButton
                  key="remove"
                  size="small"
                  danger
                  onClick={() => {
                    modal.confirm({
                      title: t('domains.remove_title', { host: domain.host }),
                      content: t('domains.remove_body'),
                      okText: t('domains.remove'),
                      okButtonProps: { danger: true },
                      cancelText: t('actions.cancel'),
                      onOk: () => removeDomain(domain),
                    });
                  }}
                  data-testid={`domain-remove-${domain.host}`}
                >
                  {t('domains.remove')}
                </WriteButton>,
              ]}
            >
              <Flex vertical gap={4} style={{ minWidth: 0 }}>
                <Space wrap>
                  <Typography.Text strong>
                    <bdi>{domain.host}</bdi>
                  </Typography.Text>
                  <ToneTag tone={STATUS_TONE[domain.status]}>
                    {t(`domain_status.${domain.status}`)}
                  </ToneTag>
                  <ToneTag tone="default">{t(`domain_tls_status.${domain.tls_status}`)}</ToneTag>
                </Space>
                {domain.failure_code != null && domain.status !== 'verified' && (
                  <Typography.Text type="danger">
                    {t(`errors.${domain.failure_code}`)}
                  </Typography.Text>
                )}
                {domain.checked_at != null && (
                  <Typography.Text type="secondary">
                    {t('domains.checked_at', { when: dates.format(domain.checked_at) })}
                  </Typography.Text>
                )}
                {domain.certificate_not_after != null && (
                  <Typography.Text type="secondary">
                    {t('domains.certificate_until', {
                      when: dates.format(domain.certificate_not_after),
                    })}
                  </Typography.Text>
                )}
              </Flex>
            </List.Item>
          )}
        />
      </Flex>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => domainPart(t, field)}
        opened={domainView(removing)}
        latest={domainView(live)}
        onReload={() => {
          conflict.clear();
          setRemoving(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (removing !== undefined && live !== undefined) {
            void removeDomain(live, conflict.latestVersion ?? live.version);
          }
          setRemoving(undefined);
        }}
      />
      <CertificateDialog
        domain={certificateFor}
        latest={data?.items.find((d) => d.id === certificateFor?.id)}
        onClose={() => {
          setCertificateFor(null);
        }}
      />
    </Card>
  );
}
