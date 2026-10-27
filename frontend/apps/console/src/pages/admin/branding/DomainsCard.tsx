import { App, Card, Flex, Input, List, Modal, Space, Tag, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  queryKeys,
  useAddDomain,
  useDomains,
  useRemoveDomain,
  useUploadCertificate,
  useVerifyDomain,
  type CustomDomain,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import { reportError, useDateTime, useLabel, WriteButton } from '@supportx/ui';

const DOMAINS_CHANGED = 'organization.domains_changed';
const STATUS_COLOUR = { pending: 'default', verified: 'success', failed: 'error' } as const;

function CertificateDialog({
  domain,
  onClose,
}: {
  domain: CustomDomain | null;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const upload = useUploadCertificate();
  const [certificate, setCertificate] = useState('');
  const [privateKey, setPrivateKey] = useState('');
  return (
    <Modal
      open={domain !== null}
      title={t('domains.certificate_title', { host: domain?.host ?? '' })}
      okText={t('domains.certificate_save')}
      cancelText={t('actions.cancel')}
      confirmLoading={upload.isPending}
      okButtonProps={{ disabled: certificate === '' || privateKey === '' }}
      destroyOnHidden
      onCancel={onClose}
      onOk={() => {
        if (domain === null) return;
        upload.mutate(
          { id: domain.id, version: domain.version, certificate, privateKey },
          {
            onSuccess: () => {
              void message.success(t('domains.certificate_saved'));
              setCertificate('');
              setPrivateKey('');
              onClose();
            },
            onError: reportError,
          },
        );
      }}
    >
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary">
          {t('domains.certificate_hint')}
        </Typography.Paragraph>
        <label htmlFor="domain-certificate">{t('domains.certificate')}</label>
        <Input.TextArea
          id="domain-certificate"
          rows={5}
          value={certificate}
          onChange={(event) => {
            setCertificate(event.target.value);
          }}
          style={{ fontFamily: 'monospace' }}
          data-testid="domain-certificate"
        />
        <label htmlFor="domain-private-key">{t('domains.private_key')}</label>
        <Input.TextArea
          id="domain-private-key"
          rows={5}
          value={privateKey}
          onChange={(event) => {
            setPrivateKey(event.target.value);
          }}
          style={{ fontFamily: 'monospace' }}
          data-testid="domain-private-key"
        />
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
  useTenantChannel((event) => {
    if (event.type === DOMAINS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.branding.domains });
    }
  });

  const data = domains.data;
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
        <Space.Compact style={{ maxWidth: 480 }}>
          <Input
            value={host}
            placeholder={t('domains.host_example')}
            aria-label={t('domains.host')}
            onChange={(event) => {
              setHost(event.target.value);
            }}
            data-testid="domains-host"
          />
          <WriteButton
            type="primary"
            disabled={host.trim() === ''}
            loading={add.isPending}
            onClick={() => {
              add.mutate(
                { host: host.trim(), key },
                {
                  onSuccess: () => {
                    setHost('');
                    setKey(crypto.randomUUID());
                  },
                  onError: reportError,
                },
              );
            }}
            data-testid="domains-add"
          >
            {t('domains.add')}
          </WriteButton>
        </Space.Compact>
        <List
          dataSource={data?.items ?? []}
          locale={{ emptyText: t('domains.none') }}
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
                      onOk: () =>
                        remove
                          .mutateAsync({ id: domain.id, version: domain.version })
                          .catch(reportError),
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
                  <Tag color={STATUS_COLOUR[domain.status]}>
                    {t(`domain_status.${domain.status}`)}
                  </Tag>
                  <Tag>{t(`domain_tls_status.${domain.tls_status}`)}</Tag>
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
      <CertificateDialog
        domain={certificateFor}
        onClose={() => {
          setCertificateFor(null);
        }}
      />
    </Card>
  );
}
