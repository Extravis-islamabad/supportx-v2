import { EditOutlined, WarningOutlined } from '@ant-design/icons';
import { Badge, Tag, Tooltip } from 'antd';

import type { IncidentCatalogue, Priority } from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { statusLabel } from './labels';

// A coloured dot plus normal text: coloured tag fills (gold, white on blue) fail WCAG contrast.
const PRIORITY_COLOURS: Record<Priority, string> = {
  p1: '#cf1322',
  p2: '#fa541c',
  p3: '#faad14',
  p4: '#8c8c8c',
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
    <Tag data-testid="inc-status" data-status={status}>
      <Badge color={colour ?? '#8c8c8c'} style={{ marginInlineEnd: 6 }} />
      {statusLabel(t, catalogue, status, locale)}
    </Tag>
  );
}

/** Priority, with a marker when set by hand (REQ-INC-010) or defaulted (REQ-INC-011). */
export function PriorityTag({ priority, source }: { priority: Priority; source: string }) {
  const t = useLabel();
  return (
    <Tag data-testid="inc-priority" data-priority={priority}>
      <Badge color={PRIORITY_COLOURS[priority]} style={{ marginInlineEnd: 6 }} />
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
      <Tag icon={<WarningOutlined />} data-testid="inc-no-sla">
        {t('incidents.no_sla')}
      </Tag>
    );
  }
  return <Tag data-testid="inc-due">{format(dueAt)}</Tag>;
}
