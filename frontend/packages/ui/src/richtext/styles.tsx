import { theme } from 'antd';

/** Editor and read-only view styles from the theme tokens (light, dark, high contrast, RTL). */
export function RichTextStyles() {
  const { token } = theme.useToken();
  return (
    <style>{`
.sx-richtext { line-height: 1.6; overflow-wrap: anywhere; }
.sx-richtext p, .sx-richtext li, .sx-richtext h2, .sx-richtext h3, .sx-richtext h4,
.sx-richtext blockquote, .sx-richtext td, .sx-richtext th { unicode-bidi: plaintext; text-align: start; }
.sx-richtext p { margin: 0 0 0.5em; }
.sx-richtext blockquote { margin: 0 0 0.5em; padding-inline-start: 12px; border-inline-start: 3px solid ${token.colorBorder}; color: ${token.colorTextSecondary}; }
.sx-richtext pre { background: ${token.colorFillTertiary}; padding: 8px; border-radius: ${String(token.borderRadius)}px; overflow-x: auto; }
.sx-richtext code { font-family: ${token.fontFamilyCode}; }
.sx-richtext a { color: ${token.colorLink}; text-decoration: underline; }
.sx-richtext table { border-collapse: collapse; margin: 0 0 0.5em; }
.sx-richtext td, .sx-richtext th { border: 1px solid ${token.colorBorder}; padding: 4px 8px; vertical-align: top; }
.sx-richtext th { background: ${token.colorFillTertiary}; font-weight: 600; }
.sx-richtext-frame { border: 1px solid ${token.colorBorder}; border-radius: ${String(token.borderRadius)}px; background: ${token.colorBgContainer}; }
.sx-richtext-frame:focus-within { border-color: ${token.colorPrimary}; box-shadow: 0 0 0 2px ${token.colorPrimaryBg}; }
.sx-richtext-invalid { border-color: ${token.colorError}; }
.sx-richtext-toolbar { padding: 4px; border-bottom: 1px solid ${token.colorBorderSecondary}; }
.sx-richtext-input { min-height: 140px; padding: 8px 11px; outline: none; color: ${token.colorText}; }
.sx-richtext-input p.is-editor-empty:first-child::before { content: attr(data-placeholder); color: ${token.colorTextPlaceholder}; float: inline-start; height: 0; pointer-events: none; }
.sx-visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
`}</style>
  );
}
