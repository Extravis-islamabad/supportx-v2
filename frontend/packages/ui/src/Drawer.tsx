import { ConfigProvider, Drawer as AntDrawer, type DrawerProps } from 'antd';
import { useContext } from 'react';

/** Where a side panel opens when no placement is given: the end of the reading direction. */
function endPlacement(direction: 'ltr' | 'rtl' | undefined): 'left' | 'right' {
  return direction === 'rtl' ? 'left' : 'right';
}

/**
 * Ant Design's Drawer, opening at the end of the reading direction: on the right in English and
 * on the left in Arabic and Urdu, mirroring the navigation (coordinator, 2026-11-13). Antd's own
 * default is the right in both directions, and its ConfigProvider cannot change it, so every
 * screen imports this one (an ESLint rule bans antd's). An explicit `placement` (top, bottom, a
 * navigation drawer at the start) is kept as given.
 */
export function Drawer({ placement, ...props }: DrawerProps) {
  const { direction } = useContext(ConfigProvider.ConfigContext);
  return <AntDrawer placement={placement ?? endPlacement(direction)} {...props} />;
}

export type { DrawerProps };
