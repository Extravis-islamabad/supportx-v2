import { Alert, Card, Flex, Popconfirm, Switch, Table, Typography } from 'antd';
import { useState } from 'react';

import {
  useSaveVendorSupportSetting,
  useSupportGrants,
  useVendorSupportSetting,
  type SupportGrant,
} from '@supportx/api-client';
import {
  EmptyText,
  FormProblem,
  ToneTag,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
  type Tone,
} from '@supportx/ui';

import { GrantDetailsDrawer } from './GrantDetailsDrawer';
import { GrantDrawer } from './GrantDrawer';

export const VENDOR_SUPPORT_ANCHOR = 'vendor-support';

const STATE_TONE: Record<SupportGrant['state'], Tone> = {
  pending_verification: 'warning',
  active: 'info',
  ended: 'default',
  revoked: 'default',
};

const OPEN: ReadonlySet<SupportGrant['state']> = new Set(['pending_verification', 'active']);

/** The opt-out (D-173 (9)): refused by the API while a grant is open; its code says so. */
function NeverAllow() {
  const t = useLabel();
  const setting = useVendorSupportSetting();
  const save = useSaveVendorSupportSetting();
  const problem = useFormProblem();
  if (setting.data === undefined) return null;
  const { never_allow: never, version } = setting.data;
  const change = (next: boolean) => {
    problem.clear();
    save.mutate(
      { neverAllow: next, version },
      {
        onError: (error) => {
          problem.show(error);
        },
      },
    );
  };
  return (
    <Flex vertical gap={8}>
      <FormProblem problem={problem} />
      <Flex gap={12} align="center" wrap>
        <Popconfirm
          title={
            never ? t('vendor_support.never.allow_confirm') : t('vendor_support.never.confirm')
          }
          okText={t('vendor_support.never.ok')}
          cancelText={t('actions.cancel')}
          onConfirm={() => {
            change(!never);
          }}
        >
          <Switch
            checked={never}
            loading={save.isPending}
            aria-label={t('vendor_support.never.label')}
            data-testid="vendor-support-never"
          />
        </Popconfirm>
        <Typography.Text>{t('vendor_support.never.label')}</Typography.Text>
      </Flex>
      <Typography.Text type="secondary">{t('vendor_support.never.explain')}</Typography.Text>
    </Flex>
  );
}

/**
 * Admin › Sign-in and security › Vendor support (WP-057 S4c-3, REQ-SEC-045, D-173): the
 * tenant's grants to named Extravis engineers. Live: a grant's change refetches the list.
 */
export function VendorSupportCard() {
  const t = useLabel();
  const { format, relative } = useDateTime();
  const grants = useSupportGrants();
  const setting = useVendorSupportSetting();
  const [granting, setGranting] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const never = setting.data?.never_allow === true;
  const rows = grants.data ?? [];
  const opened = rows.find((g) => g.id === openId);
  return (
    <Card
      id={VENDOR_SUPPORT_ANCHOR}
      title={t('vendor_support.title')}
      extra={
        <WriteButton
          type="primary"
          disabled={never}
          whyDisabled={never ? t('vendor_support.grant.never_on') : undefined}
          onClick={() => {
            setGranting(true);
          }}
          data-testid="vendor-support-grant"
        >
          {t('vendor_support.grant.action')}
        </WriteButton>
      }
      data-testid="vendor-support-card"
    >
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('vendor_support.intro')}
        </Typography.Paragraph>
        <NeverAllow />
        {rows.some((g) => OPEN.has(g.state)) && (
          <Alert type="info" showIcon message={t('vendor_support.open_notice')} />
        )}
        <Table<SupportGrant>
          rowKey="id"
          size="small"
          loading={grants.isPending}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyText>{t('vendor_support.empty')}</EmptyText> }}
          onRow={(grant) => ({
            onClick: () => {
              setOpenId(grant.id);
            },
            style: { cursor: 'pointer' },
          })}
          columns={[
            {
              key: 'engineer',
              title: t('vendor_support.column.engineer'),
              render: (_, grant) => (
                <Flex vertical>
                  <Typography.Link
                    onClick={() => {
                      setOpenId(grant.id);
                    }}
                    data-testid="vendor-support-row"
                  >
                    {grant.engineer_name}
                  </Typography.Link>
                  <Typography.Text type="secondary" dir="ltr">
                    {grant.engineer_email}
                  </Typography.Text>
                </Flex>
              ),
            },
            {
              key: 'access',
              title: t('vendor_support.column.access'),
              render: (_, grant) => t(`support_grant_access.${grant.access}`),
            },
            {
              key: 'state',
              title: t('vendor_support.column.state'),
              render: (_, grant) => (
                <ToneTag tone={STATE_TONE[grant.state]}>
                  {t(`support_grant_state.${grant.state}`)}
                </ToneTag>
              ),
            },
            {
              key: 'ends',
              title: t('vendor_support.column.ends'),
              render: (_, grant) =>
                OPEN.has(grant.state) ? (
                  <span title={format(grant.ends_at)}>{relative(grant.ends_at)}</span>
                ) : (
                  format(grant.ended_at ?? grant.ends_at)
                ),
            },
            {
              key: 'verification',
              title: t('vendor_support.column.verification'),
              render: (_, grant) => t(`support_grant_verification.${grant.verification}`),
            },
          ]}
        />
      </Flex>
      <GrantDrawer
        open={granting}
        onClose={() => {
          setGranting(false);
        }}
      />
      {opened !== undefined && (
        <GrantDetailsDrawer
          grant={opened}
          onClose={() => {
            setOpenId(null);
          }}
        />
      )}
    </Card>
  );
}
