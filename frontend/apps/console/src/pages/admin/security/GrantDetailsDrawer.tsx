import {
  App,
  Button,
  Descriptions,
  Divider,
  Flex,
  InputNumber,
  List,
  Popconfirm,
  Space,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  useEndSupportGrant,
  useExtendSupportGrant,
  useResendSupportLink,
  useSupportActivity,
  type SupportGrant,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  Drawer,
  EmptyText,
  FormProblem,
  useAccess,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

const MAX_TOTAL_HOURS = 72; // D-173: never past 72 hours from the start

function hoursLeftToExtend(grant: SupportGrant): number {
  const used = (Date.parse(grant.ends_at) - Date.parse(grant.starts_at)) / 3_600_000;
  return Math.max(0, Math.floor(MAX_TOTAL_HOURS - used));
}

/** What the grant's account did (a tenant admin who may read the audit; codes and IDs only). */
function Activity({ grantId }: { grantId: string }) {
  const t = useLabel();
  const { formatExact } = useDateTime();
  const activity = useSupportActivity(grantId);
  const items = activity.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <List
      size="small"
      loading={activity.isPending}
      dataSource={items}
      locale={{ emptyText: <EmptyText>{t('vendor_support.activity.empty')}</EmptyText> }}
      data-testid="vendor-support-activity"
      renderItem={(entry) => (
        <List.Item>
          <Flex vertical>
            <Typography.Text>
              {t(`audit.action.${entry.action}`)}
              {entry.outcome !== 'done' && (
                <Typography.Text type="secondary">
                  {' '}
                  · {t(`audit_outcome.${entry.outcome}`)}
                </Typography.Text>
              )}
            </Typography.Text>
            <Typography.Text type="secondary">{formatExact(entry.occurred_at)}</Typography.Text>
          </Flex>
        </List.Item>
      )}
      loadMore={
        activity.hasNextPage ? (
          <Flex justify="center" style={{ marginTop: 8 }}>
            <Button
              loading={activity.isFetchingNextPage}
              onClick={() => {
                void activity.fetchNextPage();
              }}
            >
              {t('vendor_support.activity.more')}
            </Button>
          </Flex>
        ) : null
      }
    />
  );
}

/** One grant: its facts, what its account did, and extend, end now or resend the link. */
export function GrantDetailsDrawer({
  grant,
  onClose,
}: {
  grant: SupportGrant;
  onClose: () => void;
}) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { message } = App.useApp();
  const { format } = useDateTime();
  const { can } = useAccess();
  const extend = useExtendSupportGrant();
  const end = useEndSupportGrant();
  const resend = useResendSupportLink();
  const problem = useFormProblem();
  const open = grant.state === 'pending_verification' || grant.state === 'active';
  // The admin's own words (free text, not codes): shown as written.
  const { reason: why, change_reason: changeWhy } = grant;
  const room = hoursLeftToExtend(grant);
  const [hours, setHours] = useState<number | null>(Math.min(4, room) || null);
  const failed = (error: unknown) => {
    problem.show(error);
  };
  return (
    <Drawer
      open
      width={640}
      title={grant.engineer_name}
      onClose={onClose}
      destroyOnHidden
      data-testid="vendor-support-details"
    >
      <Flex vertical gap={16}>
        <FormProblem problem={problem} />
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label={t('vendor_support.column.engineer')}>
            {grant.engineer_name} · <span dir="ltr">{grant.engineer_email}</span>
          </Descriptions.Item>
          <Descriptions.Item label={t('vendor_support.column.state')}>
            {t(`support_grant_state.${grant.state}`)}
          </Descriptions.Item>
          <Descriptions.Item label={t('vendor_support.column.access')}>
            {t(`support_grant_access.${grant.access}`)}
          </Descriptions.Item>
          <Descriptions.Item label={t('vendor_support.field.reason')}>{why}</Descriptions.Item>
          {changeWhy !== null && (
            <Descriptions.Item label={t('vendor_support.field.change_reason')}>
              {changeWhy}
            </Descriptions.Item>
          )}
          {grant.ticket_ref !== null && (
            <Descriptions.Item label={t('vendor_support.field.ticket_ref')}>
              <span dir="ltr">{grant.ticket_ref}</span>
            </Descriptions.Item>
          )}
          <Descriptions.Item label={t('vendor_support.field.unmask')}>
            {grant.unmask_personal ? t('vendor_support.yes') : t('vendor_support.no')}
          </Descriptions.Item>
          <Descriptions.Item label={t('vendor_support.window')}>
            {format(grant.starts_at)} – {format(grant.ended_at ?? grant.ends_at)}
          </Descriptions.Item>
          <Descriptions.Item label={t('vendor_support.column.verification')}>
            {t(`support_grant_verification.${grant.verification}`)}
          </Descriptions.Item>
          {grant.ip_allowlist.length > 0 && (
            <Descriptions.Item label={t('vendor_support.field.ip_allowlist')}>
              <span dir="ltr">{listFormat(grant.ip_allowlist)}</span>
            </Descriptions.Item>
          )}
        </Descriptions>
        {open && (
          <Flex vertical gap={12}>
            <Space wrap align="end">
              <Flex vertical gap={4}>
                <label htmlFor="vendor-support-extend-hours">
                  {t('vendor_support.extend.label')}
                </label>
                <InputNumber
                  id="vendor-support-extend-hours"
                  min={1}
                  max={Math.max(room, 1)}
                  precision={0}
                  disabled={room < 1}
                  value={hours}
                  onChange={setHours}
                  suffix={t('vendor_support.hours_unit')}
                  style={{ width: 168 }}
                  data-testid="vendor-support-extend-hours"
                />
              </Flex>
              <WriteButton
                disabled={room < 1 || hours === null}
                whyDisabled={
                  room < 1
                    ? t('vendor_support.extend.at_ceiling', { max: MAX_TOTAL_HOURS })
                    : undefined
                }
                loading={extend.isPending}
                onClick={() => {
                  problem.clear();
                  extend.mutate(
                    { id: grant.id, version: grant.version, hours: hours ?? 1 },
                    {
                      onSuccess: () => void message.success(t('vendor_support.extend.done')),
                      onError: failed,
                    },
                  );
                }}
                data-testid="vendor-support-extend"
              >
                {t('vendor_support.extend.action')}
              </WriteButton>
            </Space>
            <Space wrap>
              {grant.verification === 'email' && (
                <WriteButton
                  loading={resend.isPending}
                  onClick={() => {
                    problem.clear();
                    resend.mutate(
                      { id: grant.id },
                      {
                        onSuccess: () => void message.success(t('vendor_support.resend.done')),
                        onError: failed,
                      },
                    );
                  }}
                  data-testid="vendor-support-resend"
                >
                  {t('vendor_support.resend.action')}
                </WriteButton>
              )}
              <Popconfirm
                title={t('vendor_support.end.confirm', { name: grant.engineer_name })}
                okText={t('vendor_support.end.action')}
                okButtonProps={{ danger: true }}
                cancelText={t('actions.cancel')}
                onConfirm={() => {
                  problem.clear();
                  end.mutate(
                    { id: grant.id },
                    {
                      onSuccess: () => void message.success(t('vendor_support.end.done')),
                      onError: failed,
                    },
                  );
                }}
              >
                <WriteButton danger loading={end.isPending} data-testid="vendor-support-end">
                  {t('vendor_support.end.action')}
                </WriteButton>
              </Popconfirm>
            </Space>
          </Flex>
        )}
        {can('audit.view') && (
          <>
            <Divider orientation="left" plain>
              {t('vendor_support.activity.title')}
            </Divider>
            <Activity grantId={grant.id} />
          </>
        )}
      </Flex>
    </Drawer>
  );
}
