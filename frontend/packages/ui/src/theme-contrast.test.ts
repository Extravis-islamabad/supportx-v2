import { theme as antdTheme } from 'antd';
import { describe, expect, it } from 'vitest';

import { buildTheme, THEME_MODES } from './theme';
import { contrastRatio } from './tones';

// The palette against WCAG AA (4.5:1 for text), one deterministic check of the colours themselves.
// Arabic and Urdu use this same palette, and axe cannot measure them (docs/architecture/testing.md),
// so this is what guarantees their colours; tones.test.tsx covers the tag tones.

const AA = 4.5;

/** `#rrggbb` of a colour shown on an opaque background, blending any alpha. */
function flat(colour: string, background: string): string {
  const hex = (value: number) => Math.round(value).toString(16).padStart(2, '0');
  const channels = (text: string): number[] => {
    const short = /^#([0-9a-f]{3})$/i.exec(text)?.[1];
    if (short !== undefined) return [0, 1, 2].map((at) => parseInt(short.charAt(at).repeat(2), 16));
    const long = /^#([0-9a-f]{6})/i.exec(text)?.[1];
    if (long !== undefined) return [0, 2, 4].map((at) => parseInt(long.slice(at, at + 2), 16));
    return (text.match(/[\d.]+/g) ?? []).map(Number);
  };
  const [r = 0, g = 0, b = 0, alpha = 1] = channels(colour);
  const [br = 0, bg = 0, bb = 0] = channels(background);
  const mix = (front: number, back: number) => front * alpha + back * (1 - alpha);
  return `#${hex(mix(r, br))}${hex(mix(g, bg))}${hex(mix(b, bb))}`;
}

const TEXT = [
  'colorText',
  'colorTextSecondary',
  'colorTextTertiary',
  'colorTextDescription',
  'colorTextPlaceholder',
  'colorLink',
  'colorError',
] as const;
const SURFACES = ['colorBgContainer', 'colorBgLayout', 'colorBgElevated'] as const;

describe.each(THEME_MODES)('palette, %s', (mode) => {
  const token = antdTheme.getDesignToken(buildTheme(mode));

  it.each(TEXT)('%s reads on every surface', (name) => {
    for (const surface of SURFACES) {
      const background = flat(token[surface], '#ffffff');
      expect(
        contrastRatio(flat(token[name], background), background),
        `${name} on ${surface}`,
      ).toBeGreaterThanOrEqual(AA);
    }
  });

  it('white text reads on the primary colour', () => {
    expect(contrastRatio('#ffffff', flat(token.colorPrimary, '#ffffff'))).toBeGreaterThanOrEqual(
      AA,
    );
  });
});

describe.each(THEME_MODES)('V5: empty tables and lists, %s', (mode) => {
  it('V5: "nothing here" text in a table or list reads (not the disabled colour)', () => {
    const config = buildTheme(mode);
    const token = antdTheme.getDesignToken(config);
    for (const name of ['Table', 'List'] as const) {
      const own = config.components?.[name]?.colorTextDisabled;
      expect(own, `${name} sets its empty text colour`).toBeDefined();
      const background = flat(token.colorBgContainer, '#ffffff');
      expect(
        contrastRatio(flat(own ?? '', background), background),
        `${name} empty text`,
      ).toBeGreaterThanOrEqual(AA);
    }
  });
});

describe.each(THEME_MODES)('tabs, %s', (mode) => {
  it('a hovered or selected tab reads on its card (matrix run 42977617899)', () => {
    const config = buildTheme(mode);
    const token = antdTheme.getDesignToken(config);
    const tabs = config.components?.Tabs;
    const background = flat(token.colorBgContainer, '#ffffff');
    const shown = {
      hover: tabs?.itemHoverColor ?? token.colorPrimaryHover,
      selected: tabs?.itemSelectedColor ?? token.colorPrimary,
    };
    for (const [state, colour] of Object.entries(shown)) {
      expect(
        contrastRatio(flat(colour, background), background),
        `${state} tab`,
      ).toBeGreaterThanOrEqual(AA);
    }
  });
});
