import { Flex, Typography, theme } from 'antd';
import type { ReactNode } from 'react';

import { SPACE, TYPE } from '../density';

import { PageColumn } from './PageColumn';
import { PageHeader, type PageHeaderProps } from './PageHeader';

export interface FormPageProps {
  title: ReactNode;
  back?: PageHeaderProps['back'];
  description?: ReactNode;
  /** The sections (FormSection cards), top to bottom. */
  children: ReactNode;
  /** The secondary action, on the start side of the primary one: usually Cancel. */
  cancel?: ReactNode;
  /** The primary action, last. */
  primary: ReactNode;
  /** More in the bar, before Cancel (a refusal with no field, a draft note). */
  notice?: ReactNode;
  /** The help column beside the form on wide screens. */
  aside?: ReactNode;
  testId?: string;
}

/**
 * Template B, the form page (D-147): the header, the sections in cards, and one footer bar that
 * stays at the bottom of the window with Cancel to the start side of the primary action. No
 * buttons in the middle of the form. RTL mirrors the bar with the page.
 */
export function FormPage({
  title,
  back,
  description,
  children,
  cancel,
  primary,
  notice,
  aside,
  testId,
}: FormPageProps) {
  const { token } = theme.useToken();
  return (
    <PageColumn kind="form" aside={aside} testId={testId}>
      <PageHeader title={title} back={back} description={description} />
      <Flex vertical gap={SPACE.md}>
        {children}
      </Flex>
      <div
        data-testid={testId === undefined ? undefined : `${testId}-footer`}
        style={{
          position: 'sticky',
          bottom: 0,
          zIndex: 2,
          marginTop: SPACE.md,
          padding: `${String(SPACE.sm)}px ${String(SPACE.md)}px`,
          background: token.colorBgContainer,
          border: `1px solid ${token.colorBorderSecondary}`,
          borderRadius: token.borderRadius,
          boxShadow: token.boxShadowTertiary,
        }}
      >
        <Flex align="center" gap={SPACE.sm} wrap>
          <div style={{ flex: 1, minWidth: 0 }}>{notice}</div>
          {cancel}
          {primary}
        </Flex>
      </div>
    </PageColumn>
  );
}

/**
 * One logical section of a form, in its own card (D-147 template B): a title, an optional line
 * of help said once for the section, and the fields with labels above them.
 */
export function FormSection({
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
        minWidth: 0,
      }}
    >
      <Typography.Title level={2} style={{ margin: 0, fontSize: TYPE.section, fontWeight: 600 }}>
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

/** Fields side by side where there is room, one under the other on a phone. */
export function FieldRow({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
        columnGap: SPACE.md,
        alignItems: 'start',
      }}
    >
      {children}
    </div>
  );
}
