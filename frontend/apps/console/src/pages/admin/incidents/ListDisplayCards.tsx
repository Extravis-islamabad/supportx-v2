import { Alert, Empty, Flex, Radio, Skeleton, Table } from 'antd';

import {
  useCustomFields,
  useIncidentListDisplay,
  useIncidentListDisplayChange,
  useIncidentViewAudit,
  useRerunIncidentViewAudit,
  type RowColourBy,
  type ViewAudit,
} from '@supportx/api-client';
import {
  reportError,
  SettingsCard,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

// WP-046b S3a. The tenant's default row colouring (REQ-INC-115 AC1: people may choose their own
// per view), and the shared views the audit made private (D-176). Each saves through its own
// route, not the page's save bar.

const CHOICES: readonly RowColourBy[] = ['none', 'status', 'priority'];

export function RowColourCard() {
  const t = useLabel();
  const shown = useIncidentListDisplay();
  const change = useIncidentListDisplayChange();
  const data = shown.data;
  return (
    <SettingsCard
      title={t('settings.row_colours.title')}
      description={t('settings.row_colours.help')}
      testId="settings-row-colours"
    >
      {data === undefined ? (
        <Skeleton active paragraph={{ rows: 1 }} />
      ) : (
        <>
          <Radio.Group
            value={data.row_colour_by}
            aria-label={t('settings.row_colours.title')}
            disabled={change.isPending}
            onChange={(event) => {
              change.mutate(
                { value: event.target.value as RowColourBy, version: data.settings_version },
                { onError: reportError },
              );
            }}
            data-testid="settings-row-colours-choice"
          >
            {CHOICES.map((choice) => (
              <Radio key={choice} value={choice}>
                {t(`row_colour_by.${choice}`)}
              </Radio>
            ))}
          </Radio.Group>
        </>
      )}
    </SettingsCard>
  );
}

export function ViewAuditCard() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  // The report is the field-access administrators' (roles.manage); others never see the card.
  const allowed = useAccess().can('roles.manage');
  const report = useIncidentViewAudit(allowed);
  const rerun = useRerunIncidentViewAudit();
  const fields = useCustomFields('incident', false, allowed);
  // The field by its name, never its key (rule d): a custom field's label, else a built-in's.
  const fieldName = (key: string) => {
    if (key.startsWith('custom.')) {
      const found = fields.data?.find((f) => f.key === key.slice('custom.'.length));
      return found?.labels[locale] ?? found?.labels.en ?? t('work_item.field.custom');
    }
    return t(`work_item.field.${key}`);
  };
  if (!allowed) return null;
  return (
    <SettingsCard
      title={t('settings.view_audit.title')}
      description={t('settings.view_audit.help')}
      testId="settings-view-audit"
    >
      <Flex justify="flex-end" style={{ marginBlockEnd: 8 }}>
        <WriteButton
          loading={rerun.isPending}
          onClick={() => {
            rerun.mutate(undefined, { onError: reportError });
          }}
          data-testid="settings-view-audit-rerun"
        >
          {t('settings.view_audit.rerun')}
        </WriteButton>
      </Flex>
      {(report.data?.seal_pending ?? 0) > 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBlockEnd: 8 }}
          message={t('settings.view_audit.seal_pending', { n: report.data?.seal_pending ?? 0 })}
          data-testid="settings-view-audit-seal-pending"
        />
      )}
      {report.isError ? (
        <Alert type="warning" showIcon message={t('settings.view_audit.unavailable')} />
      ) : report.data === undefined ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : report.data.items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('settings.view_audit.none')}
          data-testid="settings-view-audit-empty"
        />
      ) : (
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={report.data.items}
          data-testid="settings-view-audit-table"
          columns={[
            { key: 'name', title: t('settings.view_audit.view'), dataIndex: 'name' },
            {
              key: 'field',
              title: t('settings.view_audit.field'),
              render: (_: unknown, row: ViewAudit['items'][number]) => fieldName(row.field),
            },
            {
              key: 'when',
              title: t('settings.view_audit.when'),
              render: (_: unknown, row: ViewAudit['items'][number]) => format(row.unshared_at),
            },
          ]}
        />
      )}
    </SettingsCard>
  );
}
