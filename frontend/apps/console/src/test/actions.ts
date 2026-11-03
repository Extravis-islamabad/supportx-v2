import { fireEvent, screen, within } from '@testing-library/react';

/**
 * The record's actions (D-124): an available everyday action is a button; every action is also
 * in "More actions", disabled with its reason when it is not available now.
 */
const BAR = 'inc-operations';

/** Open "More actions" and return its menu. */
export async function openMoreActions(bar = BAR): Promise<HTMLElement> {
  fireEvent.click(await screen.findByTestId(`${bar}-more`));
  const menus = await screen.findAllByRole('menu');
  const menu = menus.at(-1);
  if (menu === undefined) throw new Error('no actions menu');
  return menu;
}

/** The menu entry of one action (`inc-action-close` → its item in "More actions"). */
export async function actionItem(testId: string, bar = BAR): Promise<HTMLElement> {
  const menu = await openMoreActions(bar);
  return within(menu).getByTestId(`${testId}-menu`);
}

/** Run an action: its button when it has one, else its entry in "More actions". */
export async function clickAction(testId: string, bar = BAR): Promise<void> {
  await screen.findByTestId(`${bar}-more`);
  const button = screen.queryByTestId(testId);
  if (button !== null) {
    fireEvent.click(button);
    return;
  }
  fireEvent.click(await actionItem(testId, bar));
}

/** The test ids of the actions in "More actions", in their order. */
export async function actionOrder(bar = BAR): Promise<string[]> {
  const menu = await openMoreActions(bar);
  return within(menu)
    .getAllByRole('menuitem')
    .map((item) => (item.getAttribute('data-testid') ?? '').replace(/-menu$/, ''));
}

/** Whether an action's menu entry is disabled. */
export function isDisabled(item: HTMLElement): boolean {
  return item.getAttribute('aria-disabled') === 'true';
}
