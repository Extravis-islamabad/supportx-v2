import { DownOutlined, MoreOutlined } from '@ant-design/icons';
import { Button, Dropdown, Flex, type MenuProps } from 'antd';
import type { ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE } from '../density';

/** An action that lives in the header's "More" menu. */
export interface MoreAction {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  testId?: string;
}

/** Most header buttons a list or library page shows before "More" (D-147 template C). */
export const MAX_HEADER_BUTTONS = 3;

/**
 * A page header's actions (D-147 template C): at most three buttons, the primary one last
 * (it counts as one), everything else in "More". A page passes its everyday buttons in order of
 * use; the ones past the limit move into the menu ahead of `more`, so the header never grows.
 */
export function HeaderActions({
  primary,
  buttons = [],
  more = [],
  testId,
}: {
  primary?: ReactNode;
  /** Everyday buttons, most used first: those past the limit become menu entries (`overflow`). */
  buttons?: { key: string; node: ReactNode; overflow?: MoreAction }[];
  more?: MoreAction[];
  testId?: string;
}) {
  const t = useLabel();
  const room = MAX_HEADER_BUTTONS - (primary === undefined ? 0 : 1) - 1; // one place for "More"
  const shown = buttons.length + more.length > room + 1 ? buttons.slice(0, room) : buttons;
  const moved = buttons.slice(shown.length).flatMap((b) => (b.overflow ? [b.overflow] : []));
  const menu = [...moved, ...more];
  const items: MenuProps['items'] = menu.map((a) => ({
    key: a.key,
    icon: a.icon,
    disabled: a.disabled,
    danger: a.danger,
    label: <span data-testid={a.testId}>{a.label}</span>,
    onClick: a.onClick,
  }));
  return (
    <Flex gap={SPACE.xs} align="center" wrap data-testid={testId}>
      {shown.map((b) => (
        <span key={b.key}>{b.node}</span>
      ))}
      {menu.length > 0 && (
        <Dropdown trigger={['click']} menu={{ items }}>
          <Button
            icon={<MoreOutlined />}
            data-testid={testId === undefined ? undefined : `${testId}-more`}
          >
            {t('actions.more')} <DownOutlined aria-hidden />
          </Button>
        </Dropdown>
      )}
      {primary}
    </Flex>
  );
}
