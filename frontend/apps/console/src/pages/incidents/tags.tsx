import { EditOutlined, InfoCircleOutlined, WarningOutlined } from '@ant-design/icons';
import { Badge, Tag, Tooltip } from 'antd';
import { useEffect, useState } from 'react';

import { useIncidentCatalogue, type IncidentCatalogue, type Priority } from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { scaleLabel, statusLabel } from './labels';
import { PRIORITY_COLOURS } from './priorityColours';

// A coloured dot plus normal text: coloured tag fills (gold, white on blue) fail WCAG contrast.
// The tenant's colours and names win (WP-020c); these are the fallback while they load.

export function StatusTag({
  status,
  catalogue,
  testId = 'inc-status',
}: {
  status: string;
  catalogue: IncidentCatalogue | undefined;
  testId?: string;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const colour = catalogue?.statuses.find((s) => s.code === status)?.colour;
  return (
    <Tag data-testid={testId} data-status={status}>
      <Badge color={colour ?? '#8c8c8c'} style={{ marginInlineEnd: 6 }} />
      {statusLabel(t, catalogue, status, locale)}
    </Tag>
  );
}

/** Priority, with a marker when set by hand (REQ-INC-010) or defaulted (REQ-INC-011). */
export function PriorityTag({ priority, source }: { priority: Priority; source: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const catalogue = useIncidentCatalogue();
  const colour =
    catalogue.data?.scales.find((v) => v.scale === 'priority' && v.code === priority)?.colour ??
    PRIORITY_COLOURS[priority];
  return (
    <Tag data-testid="inc-priority" data-priority={priority}>
      <Badge color={colour} style={{ marginInlineEnd: 6 }} />
      {scaleLabel(t, catalogue.data, 'priority', priority, locale)}
      {source === 'manual' && (
        <Tooltip title={t('priority_source.manual')}>
          <EditOutlined aria-label={t('priority_source.manual')} style={{ marginInlineStart: 4 }} />
        </Tooltip>
      )}
      {source === 'default' && (
        // An icon with its name, as the manual pencil: a bare "*" read as a stray asterisk
        // and had no role (QA10V-17).
        <Tooltip title={t('priority_source.default')}>
          <InfoCircleOutlined
            role="img"
            aria-label={t('priority_source.default')}
            style={{ marginInlineStart: 4 }}
            data-testid="inc-priority-default"
          />
        </Tooltip>
      )}
    </Tag>
  );
}

/** REQ-INC-011: an incident without an SLA says so instead of showing nothing. */
/** Now, ticking every `everyMs` (the countdown moves on its own, REQ-SLA-038, §3.7). */
function useNow(everyMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, everyMs);
    return () => {
      window.clearInterval(timer);
    };
  }, [everyMs]);
  return now;
}

type Translate = ReturnType<typeof useLabel>;

// For screen readers only (the state is already shown by the dot and the words).
const HIDDEN = {
  position: 'absolute',
  width: 1,
  height: 1,
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
} as const;

/** A span of wall time in words: "2 d 3 h", "4 h 10 min", "25 min". */
function span(t: Translate, ms: number): string {
  const minutes = Math.max(Math.floor(ms / 60_000), 0);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days > 0) return t('incidents.sla.span_days', { days, hours });
  if (hours > 0) return t('incidents.sla.span_hours', { hours, minutes: minutes % 60 });
  return t('incidents.sla.span_minutes', { minutes });
}

/**
 * The resolution SLA at a glance: time left or overdue, ticking on the client from the due time
 * (WP-025 session 4), with the due moment on hover. The dot follows the target's state (warning
 * past its point, error once overdue). For screen readers it is a timer that is not announced
 * every minute; only a change of state is said, politely (wp-025-plan.md §3.7). Once
 * resolved there is nothing left to count: it says whether it was resolved on time (QA6-INC-03).
 */
export function SlaTag({
  policyId,
  dueAt,
  state,
  resolvedAt = null,
  format,
}: {
  policyId: string | null;
  dueAt: string | null;
  state?: string | null;
  resolvedAt?: string | null;
  format: (iso: string | null) => string;
}) {
  const t = useLabel();
  const now = useNow(30_000);
  if (policyId === null) {
    return (
      <Tag icon={<WarningOutlined />} data-testid="inc-no-sla">
        {t('incidents.no_sla')}
      </Tag>
    );
  }
  const stateText = state ? t(`sla_target_state.${state}`) : '';
  if (resolvedAt !== null && state !== 'stopped') {
    const late =
      state === 'breached' || (dueAt !== null && Date.parse(resolvedAt) > Date.parse(dueAt));
    return (
      <Tooltip title={dueAt === null ? undefined : format(dueAt)}>
        <Tag data-testid="inc-due" data-state={late ? 'resolved_late' : 'resolved_on_time'}>
          <Badge status={late ? 'error' : 'success'} />
          {t(late ? 'incidents.sla.resolved_late' : 'incidents.sla.resolved_on_time')}
        </Tag>
      </Tooltip>
    );
  }
  if (dueAt === null) {
    // Paused or done: no moment to count to.
    return <Tag data-testid="inc-due">{stateText || format(null)}</Tag>;
  }
  const left = Date.parse(dueAt) - now;
  const overdue = left < 0 || state === 'breached';
  const dot = overdue ? 'error' : state === 'warning' ? 'warning' : 'default';
  const text =
    left >= 0
      ? t('incidents.sla.due_in', { time: span(t, left) })
      : t('incidents.sla.overdue_by', { time: span(t, -left) });
  return (
    <Tooltip title={format(dueAt)}>
      <Tag data-testid="inc-due" data-state={overdue ? 'breached' : (state ?? 'running')}>
        <Badge status={dot} />
        <span role="timer" aria-live="off">
          {text}
        </span>
        <span style={HIDDEN} aria-live="polite">
          {stateText}
        </span>
      </Tag>
    </Tooltip>
  );
}
