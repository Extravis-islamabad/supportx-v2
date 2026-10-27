import { Typography } from 'antd';
import type { ReactNode } from 'react';

/**
 * A field and what is wrong with it, said at once under it (QA BUG-02, BUG-03): a check of what
 * was typed, or the server's refusal.
 */
export function FieldProblem({
  testId,
  id,
  message,
  children,
}: {
  testId: string;
  id: string;
  message: string | null;
  children: ReactNode;
}) {
  return (
    <div data-testid={testId}>
      {children}
      {message !== null && (
        <Typography.Text type="danger" role="alert" id={id} style={{ display: 'block' }}>
          {message}
        </Typography.Text>
      )}
    </div>
  );
}
