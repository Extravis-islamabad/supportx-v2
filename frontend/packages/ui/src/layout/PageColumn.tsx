import { Grid } from 'antd';
import type { ReactNode } from 'react';

/** A form's widest column (D-147 global fix 4): wide enough for two fields side by side. */
export const FORM_MAX_WIDTH = 960;
/** The side help column beside a form, when there is one. */
export const ASIDE_WIDTH = 280;

/**
 * How wide a page's content runs (D-147 global fix 4): lists take the full width; forms at most
 * `FORM_MAX_WIDTH`, at the start or centred, optionally with a help column beside them that drops
 * below the form on narrow screens. Never a half-width card with the rest of the page empty.
 */
export function PageColumn({
  kind,
  aside,
  align = 'start',
  children,
  testId,
}: {
  kind: 'form' | 'list';
  aside?: ReactNode;
  align?: 'start' | 'center';
  children: ReactNode;
  testId?: string;
}) {
  const wide = Grid.useBreakpoint().lg !== false;
  if (kind === 'list') {
    return (
      <div style={{ width: '100%', minWidth: 0 }} data-testid={testId} data-page-column="list">
        {children}
      </div>
    );
  }
  const side = aside !== undefined && wide;
  return (
    <div
      data-testid={testId}
      data-page-column="form"
      style={{
        display: 'grid',
        gridTemplateColumns: side ? `minmax(0, 1fr) ${String(ASIDE_WIDTH)}px` : 'minmax(0, 1fr)',
        gap: 24,
        maxWidth: side ? FORM_MAX_WIDTH + ASIDE_WIDTH + 24 : FORM_MAX_WIDTH,
        width: '100%',
        marginInline: align === 'center' ? 'auto' : undefined,
        alignItems: 'start',
      }}
    >
      <div style={{ minWidth: 0 }}>{children}</div>
      {aside !== undefined && <aside style={{ minWidth: 0 }}>{aside}</aside>}
    </div>
  );
}
