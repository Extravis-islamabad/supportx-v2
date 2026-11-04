import { describe, expect, it } from 'vitest';

import { CHANNEL_LOOKS } from './channelLooks';

// Every channel of REQ-INC-005 has a look, and its icon reads at 3:1 or more on its tint
// (WCAG 1.4.11, non-text contrast).
const CHANNELS = [
  'phone',
  'walk_up',
  'email',
  'portal',
  'chat',
  'virtual_agent',
  'teams',
  'slack',
  'whatsapp',
  'mobile_app',
  'api',
  'monetx',
  'alert_webhook',
];

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r ?? 0) + 0.7152 * lin(g ?? 0) + 0.0722 * lin(b ?? 0);
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
};

describe('channel icons', () => {
  it('cover every channel, each icon readable on its tint', () => {
    for (const channel of CHANNELS) {
      const look = CHANNEL_LOOKS[channel];
      expect(look, channel).toBeDefined();
      expect(contrast(look?.fg ?? '', look?.bg ?? ''), channel).toBeGreaterThanOrEqual(4.5);
    }
  });
});
