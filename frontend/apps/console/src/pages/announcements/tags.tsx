import { Badge, Tag } from 'antd';

import type {
  AnnouncementSeverity,
  AnnouncementStatus,
  AnnouncementVisibility,
} from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

// A coloured dot plus normal text: the preset gold tag fails WCAG contrast (axe, WP-012).
const SEVERITY_STATUS: Record<AnnouncementSeverity, 'processing' | 'warning' | 'error'> = {
  info: 'processing',
  warning: 'warning',
  critical: 'error',
};
const STATUS_COLOR: Record<AnnouncementStatus, string> = {
  draft: 'default',
  published: 'green',
  archived: 'default',
};
const VISIBILITY_COLOR: Record<AnnouncementVisibility, string> = {
  hidden: 'default',
  scheduled: 'purple',
  live: 'green',
  ended: 'default',
};

export function SeverityTag({ severity }: { severity: AnnouncementSeverity }) {
  const t = useLabel();
  return (
    <Badge
      status={SEVERITY_STATUS[severity]}
      text={t(`announcement_severity.${severity}`)}
      data-testid="ann-severity"
    />
  );
}

export function StatusTag({ status }: { status: AnnouncementStatus }) {
  const t = useLabel();
  return (
    <Tag color={STATUS_COLOR[status]} data-testid="ann-status">
      {t(`announcement_status.${status}`)}
    </Tag>
  );
}

export function VisibilityTag({ visibility }: { visibility: AnnouncementVisibility }) {
  const t = useLabel();
  return (
    <Tag color={VISIBILITY_COLOR[visibility]} bordered={false} data-testid="ann-visibility">
      {t(`announcement_visibility.${visibility}`)}
    </Tag>
  );
}
