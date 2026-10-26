import { Tag } from 'antd';
import type { ReactNode } from 'react';

import { useAppearance } from './appearance';
import { TAG_TONES, type Tone } from './tones';

/** A tag in a readable tone of the current theme (QA BUG-01; palette and checks in tones.ts). */
export function ToneTag({
  tone,
  icon,
  children,
  testId,
}: {
  tone: Tone;
  icon?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  const { mode } = useAppearance();
  const colours = TAG_TONES[mode][tone];
  return (
    <Tag
      icon={icon}
      data-tone={tone}
      data-testid={testId}
      style={{
        color: colours.color,
        background: colours.background,
        borderColor: colours.border,
        marginInlineEnd: 0,
      }}
    >
      {children}
    </Tag>
  );
}
