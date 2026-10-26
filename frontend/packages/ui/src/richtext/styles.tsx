import { theme } from 'antd';

import { useAppearance } from '../appearance';
import type { ThemeMode } from '../theme';
import { MAX_INDENT } from './extensions';

// The palette's real colours per theme, each at least WCAG AA (4.5:1) on that theme's
// background; high contrast goes further (7:1). Stored text only carries the code
// (`data-color="red"`), so a theme change recolours old notes too.
const TEXT: Record<ThemeMode, Record<string, string>> = {
  light: {
    red: '#cf1322',
    orange: '#ad4e00',
    green: '#237804',
    blue: '#0958d9',
    grey: 'rgba(0, 0, 0, 0.62)',
  },
  dark: {
    red: '#ff7875',
    orange: '#ffa940',
    green: '#95de64',
    blue: '#69b1ff',
    grey: 'rgba(255, 255, 255, 0.68)',
  },
  high_contrast: {
    red: '#a8071a',
    orange: '#873800',
    green: '#135200',
    blue: '#003eb3',
    grey: '#262626',
  },
};
const HIGHLIGHT: Record<ThemeMode, Record<string, string>> = {
  light: { yellow: '#fff1b8', green: '#d9f7be', blue: '#d6e4ff', pink: '#ffd6e7' },
  dark: { yellow: '#614700', green: '#274916', blue: '#10239e', pink: '#780650' },
  high_contrast: { yellow: '#fff1b8', green: '#d9f7be', blue: '#d6e4ff', pink: '#ffd6e7' },
};

/** Editor and read-only view styles from the theme tokens (light, dark, high contrast, RTL). */
export function RichTextStyles() {
  const { token } = theme.useToken();
  const { mode } = useAppearance();
  const text = { brand: token.colorPrimaryText, ...TEXT[mode] };
  const colours = Object.entries(text)
    .map(
      ([code, colour]) =>
        `.sx-richtext span[data-color="${code}"], .sx-swatch-text[data-color="${code}"] { color: ${colour}; }`,
    )
    .join('\n');
  const swatches = Object.entries(text)
    .map(([code, colour]) => `.sx-swatch-text[data-color="${code}"] { background: ${colour}; }`)
    .join('\n');
  const highlights = Object.entries(HIGHLIGHT[mode])
    .map(
      ([code, colour]) =>
        `.sx-richtext mark[data-color="${code}"], .sx-swatch-highlight[data-color="${code}"] { background: ${colour}; color: inherit; }`,
    )
    .join('\n');
  const indents = Array.from({ length: MAX_INDENT }, (_, i) => i + 1)
    .map(
      (n) =>
        `.sx-richtext [data-indent="${String(n)}"] { margin-inline-start: ${String(n * 2)}em; }`,
    )
    .join('\n');
  return (
    <style>{`
.sx-richtext { line-height: 1.6; overflow-wrap: anywhere; }
.sx-richtext p, .sx-richtext li, .sx-richtext h2, .sx-richtext h3, .sx-richtext h4,
.sx-richtext blockquote, .sx-richtext td, .sx-richtext th { unicode-bidi: plaintext; text-align: start; }
.sx-richtext p { margin: 0 0 0.5em; }
.sx-richtext h2 { font-size: 1.4em; margin: 0.6em 0 0.4em; }
.sx-richtext h3 { font-size: 1.2em; margin: 0.6em 0 0.4em; }
.sx-richtext h4 { font-size: 1.05em; margin: 0.6em 0 0.4em; }
.sx-richtext [data-align="start"] { text-align: start; }
.sx-richtext [data-align="center"] { text-align: center; }
.sx-richtext [data-align="end"] { text-align: end; }
.sx-richtext [data-align="justify"] { text-align: justify; }
${indents}
.sx-richtext blockquote { margin: 0 0 0.5em; padding-inline-start: 12px; border-inline-start: 3px solid ${token.colorBorder}; color: ${token.colorTextSecondary}; }
.sx-richtext pre { background: ${token.colorFillTertiary}; padding: 8px; border-radius: ${String(token.borderRadius)}px; overflow-x: auto; direction: ltr; text-align: left; }
.sx-richtext code { font-family: ${token.fontFamilyCode}; }
.sx-richtext hr { border: none; border-top: 1px solid ${token.colorBorder}; margin: 0.75em 0; }
.sx-richtext a { color: ${token.colorLink}; text-decoration: underline; }
.sx-richtext table { border-collapse: collapse; margin: 0 0 0.5em; }
.sx-richtext td, .sx-richtext th { border: 1px solid ${token.colorBorder}; padding: 4px 8px; vertical-align: top; }
.sx-richtext th { background: ${token.colorFillTertiary}; font-weight: 600; }
.sx-richtext span[data-type="mention"] { color: ${token.colorPrimaryText}; background: ${token.colorPrimaryBg}; border-radius: 4px; padding: 0 2px; font-weight: 500; unicode-bidi: isolate; }
${colours}
${swatches}
.sx-swatch-text:not([data-color]), .sx-swatch-highlight:not([data-color]) { border: 1px solid ${token.colorBorder}; background: ${token.colorBgContainer}; }
.sx-swatch-highlight { border: 1px solid ${token.colorBorderSecondary}; }
${highlights}
.sx-richtext-frame { border: 1px solid ${token.colorBorder}; border-radius: ${String(token.borderRadius)}px; background: ${token.colorBgContainer}; }
.sx-richtext-frame:focus-within { border-color: ${token.colorPrimary}; box-shadow: 0 0 0 2px ${token.colorPrimaryBg}; }
.sx-richtext-invalid { border-color: ${token.colorError}; }
.sx-richtext-toolbar { padding: 4px; border-bottom: 1px solid ${token.colorBorderSecondary}; }
.sx-richtext-input { min-height: 140px; padding: 8px 11px; outline: none; color: ${token.colorText}; }
/* An empty paragraph with dir=auto reads left to right: the placeholder follows the UI instead. */
html[dir="rtl"] .sx-richtext-input p.is-editor-empty:first-child { direction: rtl; }
.sx-richtext-input p.is-editor-empty:first-child::before { content: attr(data-placeholder); color: ${token.colorTextPlaceholder}; float: inline-start; height: 0; pointer-events: none; }
.sx-richtext-fullscreen { position: fixed; inset: 0; z-index: 1100; border-radius: 0; display: flex; flex-direction: column; }
.sx-richtext-fullscreen .sx-richtext-scroll { flex: 1; overflow: auto; }
.sx-richtext-fullscreen .sx-richtext-input { min-height: 100%; max-width: 960px; margin-inline: auto; }
.sx-visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
`}</style>
  );
}
