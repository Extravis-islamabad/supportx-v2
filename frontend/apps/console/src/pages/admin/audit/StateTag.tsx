import { Badge, Tag, theme } from 'antd';
import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router';

// A coloured dot on a neutral tag: Ant Design's coloured tag fills (green text on light green)
// and its default link blue fail WCAG AA contrast (axe, e2e audit journey); as incidents/tags.tsx.
const TONES: Record<string, string> = {
  success: '#389e0d',
  warning: '#d48806',
  error: '#cf1322',
  processing: '#1677ff',
  default: '#8c8c8c',
};

/** A state shown as a dot and its label (outcome, run, export, archive and restore states). */
export function StateTag({
  tone,
  children,
  style,
}: {
  tone: string | undefined;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <Tag style={style}>
      <Badge color={TONES[tone ?? 'default'] ?? TONES.default} style={{ marginInlineEnd: 6 }} />
      {children}
    </Tag>
  );
}

/** A link in the brand's text colour, underlined: it sits inside text (WCAG 1.4.1, axe). */
export function OpenLink({ to, children }: { to: string; children: ReactNode }) {
  const { token } = theme.useToken();
  return (
    <Link
      to={to}
      style={{ color: token.colorPrimaryText, textDecoration: 'underline' }}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      {children}
    </Link>
  );
}
