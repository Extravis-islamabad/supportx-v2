import type { PortalStatus } from '@supportx/api-client';
import { ToneTag, useLabel, type Tone } from '@supportx/ui';

const TONE: Record<PortalStatus, Tone> = {
  received: 'info',
  in_progress: 'purple',
  waiting_for_you: 'warning',
  resolved: 'success',
  closed: 'default',
  canceled: 'default',
  awaiting_approval: 'warning',
  rejected: 'error',
};

/** The requester's plain status (never a technician-only one: the server maps it, D3). */
export function PortalStatusTag({ status }: { status: PortalStatus }) {
  const t = useLabel();
  return (
    <ToneTag tone={TONE[status]} testId="portal-status">
      {t(`portal_status.${status}`)}
    </ToneTag>
  );
}
