import { Flex, Typography } from 'antd';
import type { ReactNode } from 'react';

/**
 * A field with what is wrong with it said at once under it (D-091, WP-017-FIX): a check of what
 * was typed, or the server's refusal. The message's ID is `<id>-problem`, for aria-describedby.
 */
export function FieldNote({
  id,
  message,
  children,
}: {
  id: string;
  message: string | null;
  children: ReactNode;
}) {
  return (
    <Flex vertical gap={4} data-testid={`${id}-field`}>
      {children}
      {message !== null && (
        <Typography.Text type="danger" role="alert" id={`${id}-problem`}>
          {message}
        </Typography.Text>
      )}
    </Flex>
  );
}
