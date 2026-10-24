import { Avatar, Flex, Tooltip, Typography, theme } from 'antd';

import type { PresenceMember } from '@supportx/realtime';

import { useLabel } from './appearance';

export interface PresenceAvatarsProps {
  /** Other connections on the same record (from useRecordChannel). */
  viewers: PresenceMember[];
  /** The signed-in user: their other windows are shown as "You (another window)". */
  selfUserId: string | null;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join('')
    .toUpperCase();
}

/** "Also viewing": one avatar per person (several windows of one person count once). */
export function PresenceAvatars({ viewers, selfUserId }: PresenceAvatarsProps) {
  const t = useLabel();
  const { token } = theme.useToken();
  // Shown name (tooltip, summary) and the person's own name (avatar initials): your other
  // window says "You (another window)" but shows your initials, not "Y(" (QA BUG-13).
  const people = new Map<string, { shown: string; own: string }>();
  for (const viewer of viewers) {
    const shown = viewer.userId === selfUserId ? t('presence.you_elsewhere') : viewer.name;
    people.set(viewer.userId || viewer.clientId, { shown, own: viewer.name });
  }
  if (people.size === 0) return null;
  const names = [...people.values()];
  const summary = t('presence.viewing', { names: names.map((n) => n.shown).join(', ') });
  return (
    <Flex align="center" gap={8} role="status" aria-label={summary} data-testid="presence">
      <Typography.Text type="secondary" aria-hidden>
        {t('presence.label')}
      </Typography.Text>
      <Avatar.Group max={{ count: 4 }} aria-hidden>
        {names.map((name) => (
          <Tooltip key={name.shown} title={name.shown}>
            {/* Brand colour, like the header avatar: white on it passes WCAG AA in every mode. */}
            <Avatar size="small" style={{ background: token.colorPrimary }}>
              {initials(name.own)}
            </Avatar>
          </Tooltip>
        ))}
      </Avatar.Group>
    </Flex>
  );
}
