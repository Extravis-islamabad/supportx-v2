import { DownOutlined } from '@ant-design/icons';
import { App, Button, Dropdown, Flex, Typography, type MenuProps } from 'antd';
import type { ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE, TYPE } from '../density';

/** One action on a record, in the record type's fixed order (REQ-WI-010, D-124). */
export interface RecordAction {
  key: string;
  label: string;
  /** The server's answer: may this user run it now. */
  allowed: boolean;
  /** Why not, already translated; shown on the disabled menu item. */
  whyNot?: string;
  onClick: () => void;
  /** A candidate for the bar's buttons (everyday actions); the rest live in the menu only. */
  primary?: boolean;
  /** Which available actions earn a button when more than `max` could (lower first). */
  rank?: number;
  /** Destructive (delete, merge, cancel): last in the menu, after a divider, always confirmed. */
  danger?: boolean;
  /**
   * The confirmation question for a destructive action. Leave it out when the action asks in
   * its own dialog (a cancel asks for its reason), so nobody is asked twice.
   */
  confirm?: string;
  icon?: ReactNode;
  loading?: boolean;
  testId?: string;
}

export interface ActionBarProps {
  /** Every action of the record, in its fixed order. */
  actions: RecordAction[];
  /** At most this many buttons (D-124: 4). */
  max?: number;
  /** Content on the end side of the bar (presence, follow). */
  extra?: ReactNode;
  testId?: string;
}

/**
 * The record's actions (D-124, updating REQ-WI-010): buttons for the everyday actions available
 * now (at most four), and "More actions" listing every action in one fixed order, unavailable
 * ones disabled with their reason, so nothing moves there; destructive ones last, confirmed.
 */
export function ActionBar({ actions, max = 4, extra, testId }: ActionBarProps) {
  const t = useLabel();
  const { modal } = App.useApp();
  const candidates = actions.filter((a) => a.primary === true && a.allowed && a.danger !== true);
  // The most useful ones get a button, shown in the record's fixed order.
  const chosen = new Set(
    [...candidates]
      .sort((a, b) => (a.rank ?? 50) - (b.rank ?? 50))
      .slice(0, max)
      .map((a) => a.key),
  );
  const buttons = candidates.filter((a) => chosen.has(a.key));

  const run = (action: RecordAction) => {
    if (!action.allowed) return;
    if (action.danger === true && action.confirm !== undefined) {
      modal.confirm({
        title: action.confirm,
        okText: action.label,
        okButtonProps: { danger: true },
        cancelText: t('actions.cancel'),
        onOk: () => {
          action.onClick();
        },
      });
      return;
    }
    action.onClick();
  };

  const item = (action: RecordAction): NonNullable<MenuProps['items']>[number] => ({
    key: action.key,
    danger: action.danger,
    disabled: !action.allowed,
    icon: action.icon,
    'data-testid': action.testId === undefined ? undefined : `${action.testId}-menu`,
    label: (
      <span>
        {action.label}
        {!action.allowed && action.whyNot !== undefined && (
          <Typography.Text
            type="secondary"
            style={{ display: 'block', fontSize: TYPE.meta, whiteSpace: 'normal', maxWidth: 280 }}
          >
            {action.whyNot}
          </Typography.Text>
        )}
      </span>
    ),
  });
  const everyday = actions.filter((a) => a.danger !== true);
  const destructive = actions.filter((a) => a.danger === true);
  const items: MenuProps['items'] = [
    ...everyday.map(item),
    ...(destructive.length > 0 && everyday.length > 0 ? [{ type: 'divider' as const }] : []),
    ...destructive.map(item),
  ];

  return (
    <Flex gap={SPACE.xs} wrap align="center" data-testid={testId} style={{ marginBlock: SPACE.xs }}>
      {buttons.map((action, index) => (
        <Button
          key={action.key}
          type={index === 0 ? 'primary' : 'default'}
          icon={action.icon}
          loading={action.loading}
          onClick={() => {
            run(action);
          }}
          data-testid={action.testId}
        >
          {action.label}
        </Button>
      ))}
      {actions.length > 0 && (
        <Dropdown
          trigger={['click']}
          menu={{
            items,
            onClick: ({ key }) => {
              const action = actions.find((a) => a.key === key);
              if (action !== undefined) run(action);
            },
          }}
        >
          <Button data-testid={testId === undefined ? undefined : `${testId}-more`}>
            {t('layout.more_actions')} <DownOutlined aria-hidden />
          </Button>
        </Dropdown>
      )}
      {extra !== undefined && (
        <Flex gap={SPACE.xs} align="center" style={{ marginInlineStart: 'auto' }}>
          {extra}
        </Flex>
      )}
    </Flex>
  );
}
