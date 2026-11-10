import { Tag, Tooltip } from 'antd';

import { useAppearance, useLabel } from '../appearance';
import { CHANNEL_LOOKS, FALLBACK_LOOK } from './channelLooks';

// Where a work item came from (REQ-INC-005): see ./channelLooks.

export interface ChannelIconProps {
  channel: string;
  /** 26 on list rows, 44 in the record header. */
  size?: number;
}

/** A channel's icon in its tinted square, named by the channel's label. */
export function ChannelIcon({ channel, size = 26 }: ChannelIconProps) {
  const t = useLabel();
  const { mode } = useAppearance();
  const look = CHANNEL_LOOKS[channel] ?? FALLBACK_LOOK;
  const tint = mode === 'dark' ? look.dark : look;
  const name = t(`work_item_channel.${channel}`);
  return (
    <Tooltip title={name}>
      <span
        role="img"
        aria-label={name}
        data-testid={`channel-${channel}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          width: size,
          height: size,
          borderRadius: size > 32 ? 10 : 6,
          background: tint.bg,
          color: tint.fg,
          fontSize: Math.round(size * 0.54),
        }}
      >
        {look.icon}
      </span>
    </Tooltip>
  );
}

/**
 * A channel as a chip, with that channel's own icon (Haider, 2026-11-10: a phone call showed a
 * globe). Every chip and tile names the channel through the same looks as ChannelIcon.
 */
export function ChannelTag({ channel }: { channel: string }) {
  const t = useLabel();
  const look = CHANNEL_LOOKS[channel] ?? FALLBACK_LOOK;
  return (
    <Tag icon={<span aria-hidden>{look.icon}</span>} data-testid={`channel-tag-${channel}`}>
      {t(`work_item_channel.${channel}`)}
    </Tag>
  );
}
