import { Typography, theme } from 'antd';
import type { ReactNode } from 'react';

import { SPACE, TYPE } from '../density';

/**
 * One group of settings in its own card (D-147 template E): a title, one line of help said once
 * for the group, and the fields with labels above them. No save button inside: the page's one
 * StickySaveBar saves every card at once.
 */
export function SettingsCard({
  title,
  description,
  children,
  testId,
}: {
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  const { token } = theme.useToken();
  return (
    <section
      data-testid={testId}
      style={{
        background: token.colorBgContainer,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadius,
        padding: `${String(SPACE.md)}px ${String(SPACE.lg)}px ${String(SPACE.xs)}px`,
        marginBottom: SPACE.md,
        minWidth: 0,
      }}
    >
      <Typography.Title level={3} style={{ margin: 0, fontSize: TYPE.section, fontWeight: 600 }}>
        {title}
      </Typography.Title>
      {description !== undefined && (
        <Typography.Paragraph type="secondary" style={{ margin: `${String(SPACE.xxs)}px 0 0` }}>
          {description}
        </Typography.Paragraph>
      )}
      <div style={{ marginTop: SPACE.md }}>{children}</div>
    </section>
  );
}
