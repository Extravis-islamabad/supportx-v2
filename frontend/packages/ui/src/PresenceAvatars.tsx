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
  const people = new Map<string, string>();
  for (const viewer of viewers) {
    const name = viewer.userId === selfUserId ? t('presence.you_elsewhere') : viewer.name;
    people.set(viewer.userId || viewer.clientId, name);
  }
  if (people.size === 0) return null;
  const names = [...people.values()];
  const summary = t('presence.viewing', { names: names.join(', ') });
  return (
    <Flex align="center" gap={8} role="status" aria-label={summary} data-testid="presence">
      <Typography.Text type="secondary" aria-hidden>
        {t('presence.label')}
      </Typography.Text>
      <Avatar.Group max={{ count: 4 }} aria-hidden>
        {names.map((name) => (
          <Tooltip key={name} title={name}>
            {/* Brand colour, like the header avatar: white on it passes WCAG AA in every mode. */}
            <Avatar size="small" style={{ background: token.colorPrimary }}>
              {initials(name)}
            </Avatar>
          </Tooltip>
        ))}
      </Avatar.Group>
    </Flex>
  );
}
