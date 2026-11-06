import { MoreOutlined } from '@ant-design/icons';
import { Button, Dropdown, Flex, type MenuProps } from 'antd';

import { useLabel } from '../appearance';
import { SPACE } from '../density';

export interface RowAction {
  key: string;
  label: string;
  onClick: () => void;
  /** Destructive: last in the menu, red. The caller confirms. */
  danger?: boolean;
  disabled?: boolean;
  testId?: string;
}

/**
 * The one way a table row offers actions (QA6S-SHELL-10): its main action as a link, the rest in
 * a "…" menu named for the row, destructive ones last and red. No icon-only buttons.
 */
export function RowActions({
  primary,
  more = [],
  rowName,
}: {
  primary?: RowAction;
  more?: RowAction[];
  /** For the menu's accessible name: "More actions for Dubai office". */
  rowName: string;
}) {
  const t = useLabel();
  const ordered = [
    ...more.filter((a) => a.danger !== true),
    ...more.filter((a) => a.danger === true),
  ];
  const items: MenuProps['items'] = ordered.map((a) => ({
    key: a.key,
    label: <span data-testid={a.testId}>{a.label}</span>,
    danger: a.danger,
    disabled: a.disabled,
    onClick: a.onClick,
  }));
  return (
    <Flex gap={SPACE.xs} align="center" justify="flex-end" wrap={false}>
      {primary !== undefined && (
        <Button
          type="link"
          size="small"
          onClick={primary.onClick}
          disabled={primary.disabled}
          data-testid={primary.testId}
        >
          {primary.label}
        </Button>
      )}
      {items.length > 0 && (
        <Dropdown trigger={['click']} menu={{ items }}>
          <Button
            type="text"
            size="small"
            icon={<MoreOutlined />}
            aria-label={t('settings.row_more', { name: rowName })}
          />
        </Dropdown>
      )}
    </Flex>
  );
}
