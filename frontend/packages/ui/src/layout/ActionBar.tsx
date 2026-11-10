import { DownOutlined } from '@ant-design/icons';
import { App, Button, Dropdown, Flex, Typography, type MenuProps } from 'antd';
import { cloneElement, isValidElement, type ReactNode } from 'react';

import { useLabel } from '../appearance';
import { useLicence } from '../licence/context';
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
  /** The confirmation's buttons; by default the action's label and "Cancel". */
  confirmOk?: string;
  confirmCancel?: string;
  icon?: ReactNode;
  loading?: boolean;
  testId?: string;
  /**
   * Other ways to run it (Reply: reply to all, forward), in a dropdown on its button, so the
   * header holds the record's one Reply (D-155). In "More" they follow the action.
   */
  variants?: { key: string; label: string; onClick: () => void; testId?: string }[];
}

export interface ActionBarProps {
  /** Every action of the record, in its fixed order. */
  actions: RecordAction[];
  /** At most this many buttons (D-124: 4). */
  max?: number;
  /** Content on the end side of the bar. */
  extra?: ReactNode;
  /**
   * Content before the buttons, on the same row and aligned with them (template A: presence and
   * Follow sit with the actions, D-147).
   */
  lead?: ReactNode;
  testId?: string;
}

/**
 * The record's actions (D-124, updating REQ-WI-010): buttons for the everyday actions available
 * now (at most four), and "More actions": the available ones first, then the unavailable ones
 * grouped under their reason (said once), destructive ones last, confirmed.
 */
type MenuItem = NonNullable<MenuProps['items']>[number];

export function ActionBar({ actions: given, max = 4, extra, lead, testId }: ActionBarProps) {
  const t = useLabel();
  const { modal } = App.useApp();
  const { writable } = useLicence();
  // The read-only licence state disables every action, with its reason (WriteButton's rule).
  const actions = writable
    ? given
    : given.map((a) => ({ ...a, allowed: false, whyNot: t('licence.read_only_action') }));
  const candidates = actions.filter((a) => a.primary === true && a.allowed && a.danger !== true);
  // The most useful ones get a button, shown in the record's fixed order.
  const chosen = new Set(
    [...candidates]
      .sort((a, b) => (a.rank ?? 50) - (b.rank ?? 50))
      .slice(0, max)
      .map((a) => a.key),
  );
  const buttons = candidates.filter((a) => chosen.has(a.key));
  // The most useful one is the primary button; placement keeps the fixed order.
  const main = [...buttons].sort((a, b) => (a.rank ?? 50) - (b.rank ?? 50))[0]?.key;

  const run = (action: RecordAction) => {
    if (!action.allowed) return;
    if (action.danger === true && action.confirm !== undefined) {
      modal.confirm({
        title: action.confirm,
        okText: action.confirmOk ?? action.label,
        okButtonProps: { danger: true },
        cancelText: action.confirmCancel ?? t('actions.cancel'),
        onOk: () => {
          action.onClick();
        },
      });
      return;
    }
    action.onClick();
  };

  const item = (action: RecordAction): MenuItem => ({
    key: action.key,
    danger: action.danger,
    disabled: !action.allowed,
    icon: action.icon,
    'data-testid': action.testId === undefined ? undefined : `${action.testId}-menu`,
    label: (
      <span data-also-above={chosen.has(action.key) ? 'true' : undefined}>
        {action.label}
        {/* Also a button on the bar: the menu keeps REQ-WI-010's full fixed order, so the
            repeat is marked rather than dropped (QA10-P4-24, P1-20; coordinator option c). */}
        {chosen.has(action.key) && (
          <Typography.Text type="secondary" style={{ fontSize: TYPE.meta, marginInlineStart: 8 }}>
            {t('layout.also_above')}
          </Typography.Text>
        )}
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
  // Unavailable everyday actions, grouped under their reason, said once (QA6-INC-02: ten items
  // each repeating "Not possible in the current status" made the menu a wall). They stay in the
  // menu, in their fixed order within each group, so REQ-WI-010 still says why.
  const available = everyday.filter((a) => a.allowed);
  const reasons = new Map<string, RecordAction[]>();
  for (const action of everyday.filter((a) => !a.allowed)) {
    const why = action.whyNot ?? '';
    reasons.set(why, [...(reasons.get(why) ?? []), action]);
  }
  const unavailable: MenuItem[] = [...reasons].map(([why, group], index) => ({
    type: 'group' as const,
    key: `unavailable-${String(index)}`,
    label: why === '' ? t('layout.not_available_now') : why,
    children: group.map((action) => ({
      key: action.key,
      disabled: true,
      icon: action.icon,
      'data-testid': action.testId === undefined ? undefined : `${action.testId}-menu`,
      // The reason is the group's heading on screen; a screen reader hears it with each item.
      label: (
        <span>
          {action.label}
          {why !== '' && <span className="sx-visually-hidden">{`: ${why}`}</span>}
        </span>
      ),
    })),
  }));
  const withVariants = (action: RecordAction): MenuItem[] => [
    item(action),
    ...(action.variants ?? []).map((v) => ({
      key: `${action.key}:${v.key}`,
      label: (
        <span data-testid={v.testId === undefined ? undefined : `${v.testId}-menu`}>{v.label}</span>
      ),
    })),
  ];
  const items: MenuItem[] = [
    // A split button on the bar holds its variants in its own dropdown: not repeated here
    // (QA bug 7). A plain bar button keeps its muted "Also above" entry (REQ-WI-010's order).
    ...available
      .filter((a) => !(chosen.has(a.key) && (a.variants?.length ?? 0) > 0))
      .flatMap(withVariants),
    ...(available.length > 0 && unavailable.length > 0 ? [{ type: 'divider' as const }] : []),
    ...unavailable,
    ...(destructive.length > 0 && everyday.length > 0 ? [{ type: 'divider' as const }] : []),
    ...destructive.map(item),
  ];

  return (
    <Flex gap={SPACE.xs} wrap align="center" data-testid={testId} style={{ marginBlock: SPACE.xs }}>
      {lead}
      {buttons.map((action) =>
        action.variants !== undefined && action.variants.length > 0 ? (
          <Dropdown.Button
            key={action.key}
            // Ant Design's split button is a full-width block: in a wrapping row it took a line
            // of its own and broke the header's one row of actions (D-155, the after shots).
            style={{ width: 'auto' }}
            type={action.key === main ? 'primary' : 'default'}
            loading={action.loading}
            trigger={['click']}
            icon={<DownOutlined aria-hidden />}
            onClick={() => {
              run(action);
            }}
            menu={{
              items: action.variants.map((v) => ({
                key: v.key,
                label: <span data-testid={v.testId}>{v.label}</span>,
              })),
              onClick: ({ key }) => {
                action.variants?.find((v) => v.key === key)?.onClick();
              },
            }}
            buttonsRender={([left, right]) => [
              <span key="main" data-testid={action.testId}>
                {left}
              </span>,
              <span
                key="more"
                data-testid={action.testId === undefined ? undefined : `${action.testId}-more`}
              >
                {/* The chevron has only an icon: it needs its own name (QA10V-03, axe button-name). */}
                {isValidElement<{ 'aria-label'?: string }>(right)
                  ? cloneElement(right, {
                      'aria-label': t('layout.more_options_for', { action: action.label }),
                    })
                  : right}
              </span>,
            ]}
          >
            {action.icon}
            {action.label}
          </Dropdown.Button>
        ) : (
          <Button
            key={action.key}
            type={action.key === main ? 'primary' : 'default'}
            icon={action.icon}
            loading={action.loading}
            onClick={() => {
              run(action);
            }}
            data-testid={action.testId}
          >
            {action.label}
          </Button>
        ),
      )}
      {actions.length > 0 && (
        <Dropdown
          trigger={['click']}
          menu={{
            items,
            onClick: ({ key }) => {
              const [base, variant] = key.split(':');
              const action = actions.find((a) => a.key === base);
              if (action === undefined) return;
              if (variant === undefined) run(action);
              else action.variants?.find((v) => v.key === variant)?.onClick();
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
