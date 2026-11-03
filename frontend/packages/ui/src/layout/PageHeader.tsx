import { ArrowLeftOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { Button, Flex, Typography } from 'antd';
import type { ReactNode } from 'react';

import { useAppearance } from '../appearance';
import { SPACE, TYPE } from '../density';

export interface PageHeaderProps {
  title: ReactNode;
  /** A count beside the title (rows in the list, items in the inbox). */
  count?: ReactNode;
  /** A back link: its accessible name and what it does (the app owns routing). */
  back?: { label: string; onClick: () => void };
  /** Page actions on the end side: at most three, the main one last. */
  extra?: ReactNode;
  /** A line under the title (help or context), secondary text. */
  description?: ReactNode;
  /** 2 when the page sits inside another page that owns the h1 (a dashboard on Home). */
  level?: 1 | 2;
  testId?: string;
}

/** The one page header of the console (docs/architecture/console-design.md, D-124). */
export function PageHeader({
  title,
  count,
  back,
  extra,
  description,
  level = 1,
  testId,
}: PageHeaderProps) {
  const { direction } = useAppearance();
  return (
    <header style={{ marginBottom: SPACE.sm }} data-testid={testId}>
      <Flex justify="space-between" align="center" wrap gap={SPACE.sm}>
        <Flex align="center" gap={SPACE.xs} style={{ minWidth: 0 }}>
          {back !== undefined && (
            <Button
              type="text"
              size="small"
              aria-label={back.label}
              icon={direction === 'rtl' ? <ArrowRightOutlined /> : <ArrowLeftOutlined />}
              onClick={back.onClick}
            />
          )}
          <Typography.Title
            level={level}
            style={{ margin: 0, fontSize: level === 1 ? TYPE.page : TYPE.record, lineHeight: 1.4 }}
            ellipsis
          >
            {title}
          </Typography.Title>
          {count !== undefined && (
            <Typography.Text type="secondary" style={{ fontSize: TYPE.body }}>
              {count}
            </Typography.Text>
          )}
        </Flex>
        {extra !== undefined && (
          <Flex gap={SPACE.xs} wrap align="center">
            {extra}
          </Flex>
        )}
      </Flex>
      {description !== undefined && (
        <Typography.Paragraph type="secondary" style={{ margin: `${String(SPACE.xxs)}px 0 0` }}>
          {description}
        </Typography.Paragraph>
      )}
    </header>
  );
}
