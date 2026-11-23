import { App, Button, Card, Flex, Form, Input, Modal, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  useAddVerifiedDomain,
  useCheckVerifiedDomain,
  useRemoveVerifiedDomain,
  useVerifiedDomains,
  useVerifyDomainManually,
  type VerifiedDomain,
  type VerifiedDomainAdded,
} from '@supportx/api-client';
import {
  EmptyText,
  lengthLimit,
  reportError,
  ToneTag,
  useDateTime,
  useLabel,
  type Tone,
} from '@supportx/ui';

const STATE_TONE: Record<VerifiedDomain['state'], Tone> = {
  pending: 'info',
  verified: 'success',
  lapsed: 'warning',
};

/** The record to publish, shown this once (only its hash is kept). */
function RecordDialog({ added, onClose }: { added: VerifiedDomainAdded; onClose: () => void }) {
  const t = useLabel();
  return (
    <Modal
      open
      title={t('verified_domains.record.title', { domain: added.domain })}
      onCancel={onClose}
      footer={<Button onClick={onClose}>{t('actions.close')}</Button>}
      data-testid="domain-record"
    >
      <Typography.Paragraph>{t('verified_domains.record.intro')}</Typography.Paragraph>
      <Typography.Text type="secondary">{t('verified_domains.record.name')}</Typography.Text>
      <Typography.Paragraph code copyable={{ text: added.record_name }} dir="ltr">
        {added.record_name}
      </Typography.Paragraph>
      <Typography.Text type="secondary">{t('verified_domains.record.value')}</Typography.Text>
      <Typography.Paragraph code copyable={{ text: added.record_value }} dir="ltr">
        {added.record_value}
      </Typography.Paragraph>
      <Typography.Paragraph type="warning">
        {t('verified_domains.record.once')}
      </Typography.Paragraph>
    </Modal>
  );
}

/** Verify without DNS: for installations with no DNS to ask; the reason is audited. */
function ManualDialog({ domain, onClose }: { domain: VerifiedDomain; onClose: () => void }) {
  const t = useLabel();
  const verify = useVerifyDomainManually();
  const [reason, setReason] = useState('');
  return (
    <Modal
      open
      title={t('verified_domains.manual.title', { domain: domain.domain })}
      okText={t('verified_domains.manual.confirm')}
      okButtonProps={{ disabled: reason.trim().length < 3, loading: verify.isPending }}
      onOk={() => {
        verify.mutate(
          { id: domain.id, version: domain.version, reason: reason.trim() },
          {
            onSuccess: onClose,
            onError: (error) => {
              reportError(error);
            },
          },
        );
      }}
      onCancel={onClose}
      data-testid="domain-manual"
    >
      <Typography.Paragraph>{t('verified_domains.manual.intro')}</Typography.Paragraph>
      <Form layout="vertical">
        <Form.Item label={t('verified_domains.manual.reason')} required>
          <Input.TextArea
            value={reason}
            count={lengthLimit(500)}
            onChange={(event) => {
              setReason(event.target.value);
            }}
            data-testid="domain-manual-reason"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/**
 * Verified e-mail domains (WP-057 S5d, REQ-SEC-010): add a domain, publish the TXT record it
 * gives (shown once), and check it. A verified domain is the organisation's: sign-ins in it go to
 * its single sign-on, and no other organisation can claim it. Live through the identity channel.
 */
export function DomainsCard() {
  const t = useLabel();
  const { modal, message } = App.useApp();
  const { format } = useDateTime();
  const domains = useVerifiedDomains();
  const add = useAddVerifiedDomain();
  const check = useCheckVerifiedDomain();
  const remove = useRemoveVerifiedDomain();
  const [draft, setDraft] = useState('');
  const [manual, setManual] = useState<VerifiedDomain | null>(null);
  const added = add.data ?? null;

  const submit = () => {
    add.mutate(
      { domain: draft.trim(), key: crypto.randomUUID() },
      {
        onSuccess: () => {
          setDraft('');
        },
        onError: (error) => {
          reportError(error);
        },
      },
    );
  };

  return (
    <Card title={t('verified_domains.title')} data-testid="domains-card">
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {t('verified_domains.intro')}
        </Typography.Paragraph>
        <Flex gap={8} wrap>
          <Input
            value={draft}
            placeholder={t('verified_domains.add.placeholder')}
            aria-label={t('verified_domains.add.label')}
            style={{ maxWidth: 320 }}
            dir="ltr"
            onChange={(event) => {
              setDraft(event.target.value);
            }}
            onPressEnter={submit}
            data-testid="domains-add-input"
          />
          <Button
            type="primary"
            disabled={draft.trim() === ''}
            loading={add.isPending}
            onClick={submit}
            data-testid="domains-add"
          >
            {t('verified_domains.add.button')}
          </Button>
        </Flex>
        <Table<VerifiedDomain>
          rowKey="id"
          size="small"
          loading={domains.isLoading}
          dataSource={domains.data ?? []}
          pagination={false}
          scroll={{ x: true }}
          locale={{ emptyText: <EmptyText>{t('verified_domains.none')}</EmptyText> }}
          data-testid="domains-list"
          columns={[
            {
              key: 'domain',
              title: t('verified_domains.column.domain'),
              render: (_, row) => <span dir="ltr">{row.domain}</span>,
            },
            {
              key: 'state',
              title: t('verified_domains.column.state'),
              render: (_, row) => (
                <ToneTag tone={STATE_TONE[row.state]}>
                  {t(`verified_domain_state.${row.state}`)}
                </ToneTag>
              ),
            },
            {
              key: 'checked',
              title: t('verified_domains.column.checked'),
              render: (_, row) =>
                row.last_checked_at === null ? (
                  t('verified_domains.never_checked')
                ) : (
                  <Flex vertical>
                    <span>{format(row.last_checked_at)}</span>
                    {row.last_outcome !== null && (
                      <Typography.Text type="secondary">
                        {t(`domain_check.${row.last_outcome}`)}
                      </Typography.Text>
                    )}
                  </Flex>
                ),
            },
            {
              key: 'actions',
              title: t('verified_domains.column.actions'),
              render: (_, row) => (
                <Flex gap={8} wrap>
                  {row.state !== 'verified' && (
                    <Button
                      size="small"
                      loading={check.isPending && check.variables.id === row.id}
                      onClick={() => {
                        check.mutate(
                          { id: row.id },
                          {
                            onSuccess: (result) => {
                              void message.info(t(`domain_check.${result.outcome}`));
                            },
                            onError: (error) => {
                              reportError(error);
                            },
                          },
                        );
                      }}
                      data-testid={`domain-check-${row.domain}`}
                    >
                      {t('verified_domains.check')}
                    </Button>
                  )}
                  {row.state !== 'verified' && (
                    <Button
                      size="small"
                      onClick={() => {
                        setManual(row);
                      }}
                      data-testid={`domain-manual-${row.domain}`}
                    >
                      {t('verified_domains.manual.button')}
                    </Button>
                  )}
                  <Button
                    size="small"
                    danger
                    onClick={() => {
                      void modal.confirm({
                        title: t('verified_domains.remove.title', { domain: row.domain }),
                        content: t('verified_domains.remove.body'),
                        okText: t('verified_domains.remove.confirm'),
                        okButtonProps: { danger: true },
                        onOk: () =>
                          remove
                            .mutateAsync({ id: row.id, version: row.version })
                            .catch((error: unknown) => {
                              reportError(error);
                            }),
                      });
                    }}
                    data-testid={`domain-remove-${row.domain}`}
                  >
                    {t('verified_domains.remove.button')}
                  </Button>
                </Flex>
              ),
            },
          ]}
        />
      </Flex>
      {added !== null && (
        <RecordDialog
          added={added}
          onClose={() => {
            add.reset();
          }}
        />
      )}
      {manual !== null && (
        <ManualDialog
          domain={manual}
          onClose={() => {
            setManual(null);
          }}
        />
      )}
    </Card>
  );
}
