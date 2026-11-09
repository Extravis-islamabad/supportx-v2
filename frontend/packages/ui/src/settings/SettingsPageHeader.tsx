import { MoreOutlined } from '@ant-design/icons';
import { Button, Dropdown, Flex, Typography, type MenuProps } from 'antd';
import type { ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE, TYPE } from '../density';

export interface SettingsAction {
  key: string;
  label: string;
  onClick: () => void;
  /** Destructive: last in the menu, red. The caller confirms (ConfirmDialog patterns). */
  danger?: boolean;
  disabled?: boolean;
  /** Why it is disabled, already translated: shown in its tooltip (no unexplained disabled). */
  whyNot?: string;
  testId?: string;
}

export interface SettingsPageHeaderProps {
  /** The page's name (level 2 under the shell's "Setup"). Required on every settings page. */
  title: string;
  /** One line under it: what the page is for. Required. */
  description: ReactNode;
  /** At most one primary button ("Add site"). */
  primaryAction?: ReactNode;
  /** Up to three secondary actions; more go in a "…" menu, destructive ones last. */
  actions?: SettingsAction[];
  testId?: string;
}

const SHOWN = 2; // secondary buttons beside the primary before the "…" menu: 4 at most in all

/**
 * The one header of every settings page (QA6S-SHELL-01): the title, a one-line description and
 * at most four actions, one of them primary. Sub-navigation (tabs) goes under it.
 */
export function SettingsPageHeader({
  title,
  description,
  primaryAction,
  actions = [],
  testId,
}: SettingsPageHeaderProps) {
  const t = useLabel();
  const everyday = actions.filter((a) => a.danger !== true);
  const shown = everyday.slice(0, SHOWN);
  const rest = [...everyday.slice(SHOWN), ...actions.filter((a) => a.danger === true)];
  const items: MenuProps['items'] = rest.map((a) => ({
    key: a.key,
    label: (
      <span data-testid={a.testId}>
        {a.label}
        {a.disabled === true && a.whyNot !== undefined && (
          <Typography.Text type="secondary" style={{ display: 'block', fontSize: TYPE.meta }}>
            {a.whyNot}
          </Typography.Text>
        )}
      </span>
    ),
    danger: a.danger,
    disabled: a.disabled,
    onClick: a.onClick,
  }));
  return (
    <header data-testid={testId} style={{ marginBottom: SPACE.md }}>
      <Flex justify="space-between" align="flex-start" wrap gap={SPACE.sm}>
        <div style={{ minWidth: 0, flex: '1 1 320px' }}>
          <Typography.Title level={2} style={{ margin: 0, fontSize: 20, lineHeight: 1.4 }}>
            {title}
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ margin: 0, fontSize: TYPE.body }}>
            {description}
          </Typography.Paragraph>
        </div>
        <Flex gap={SPACE.xs} wrap align="center">
          {shown.map((a) => (
            <Button
              key={a.key}
              onClick={a.onClick}
              disabled={a.disabled}
              title={a.disabled === true ? a.whyNot : undefined}
              data-testid={a.testId}
            >
              {a.label}
            </Button>
          ))}
          {rest.length > 0 && (
            <Dropdown trigger={['click']} menu={{ items }}>
              <Button icon={<MoreOutlined />} aria-label={t('layout.more_actions')} />
            </Dropdown>
          )}
          {primaryAction}
        </Flex>
      </Flex>
    </header>
  );
}
