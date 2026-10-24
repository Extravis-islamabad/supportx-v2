import { EditOutlined } from '@ant-design/icons';
import { Tag, Tooltip } from 'antd';

import type { IncidentCatalogue, Priority } from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { statusLabel } from './labels';

const PRIORITY_COLOURS: Record<Priority, string> = {
  p1: 'red',
  p2: 'volcano',
  p3: 'gold',
  p4: 'default',
};

export function StatusTag({
  status,
  catalogue,
}: {
  status: string;
  catalogue: IncidentCatalogue | undefined;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const colour = catalogue?.statuses.find((s) => s.code === status)?.colour;
  return (
    <Tag color={colour} data-testid="inc-status" data-status={status}>
      {statusLabel(t, catalogue, status, locale)}
    </Tag>
  );
}

/** Priority, with a marker when set by hand (REQ-INC-010) or defaulted (REQ-INC-011). */
export function PriorityTag({ priority, source }: { priority: Priority; source: string }) {
  const t = useLabel();
  return (
    <Tag color={PRIORITY_COLOURS[priority]} data-testid="inc-priority" data-priority={priority}>
      {t(`priority.${priority}`)}
      {source === 'manual' && (
        <Tooltip title={t('priority_source.manual')}>
          <EditOutlined aria-label={t('priority_source.manual')} style={{ marginInlineStart: 4 }} />
        </Tooltip>
      )}
      {source === 'default' && (
        <Tooltip title={t('priority_source.default')}>
          <span aria-label={t('priority_source.default')} style={{ marginInlineStart: 4 }}>
            *
          </span>
        </Tooltip>
      )}
    </Tag>
  );
}

/** REQ-INC-011: an incident without an SLA says so instead of showing nothing. */
export function SlaTag({
  policyId,
  dueAt,
  format,
}: {
  policyId: string | null;
  dueAt: string | null;
  format: (iso: string | null) => string;
}) {
  const t = useLabel();
  if (policyId === null) {
    return (
      <Tag color="warning" data-testid="inc-no-sla">
        {t('incidents.no_sla')}
      </Tag>
    );
  }
  return <Tag data-testid="inc-due">{format(dueAt)}</Tag>;
}
