import { Typography } from 'antd';
import type { ReactNode } from 'react';

/**
 * The text of an empty table or list (`locale={{ emptyText: <EmptyText>…</EmptyText> }}`).
 *
 * A plain string there takes Ant Design's "disabled" colour, about 2:1 on white: below WCAG AA
 * (axe, found by WP-018 on the incidents and announcements tables). Secondary text passes in
 * every theme.
 */
export function EmptyText({ children }: { children: ReactNode }) {
  return (
    <Typography.Text type="secondary" data-testid="empty-text">
      {children}
    </Typography.Text>
  );
}
