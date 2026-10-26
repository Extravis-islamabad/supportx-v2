import { DownOutlined, LockOutlined } from '@ant-design/icons';
import { Grid, Layout, Menu, Tooltip, theme, type MenuProps } from 'antd';
import { useState, type ReactNode } from 'react';

import type { NavLayout } from '@supportx/api-client';

import { useLabel } from '../appearance';
import { BrandLogo } from '../brand';
import type { VisibleNavItem } from './nav';

export interface AppShellProps {
  nav: VisibleNavItem[];
  /** Key of the section being shown. */
  activeKey: string | undefined;
  onNavigate: (path: string) => void;
  /**
   * The header. With the top-bar layout the navigation lives inside the header row: the shell
   * passes it in (`topNav`), and the header places it after the brand.
   */
  header: ReactNode | ((topNav: ReactNode) => ReactNode);
  /** Licence and connectivity banners, above the page. */
  banners?: ReactNode;
  /** Where the navigation sits (the user's preference, stored server-side). Default: top bar. */
  layout?: NavLayout;
  children: ReactNode;
}

/**
 * Console layout in three variants (a per-user choice):
 * - `top`: brand and a horizontal menu in the header, a "More" menu for what does not fit; the
 *   page keeps the full width (tables).
 * - `side`: a collapsible sidebar with labels.
 * - `side_compact`: a narrow sidebar with icons only (labels as tooltips and accessible names).
 * Menu items are the same in all three (permission- and licence-driven, see `visibleNav`).
 * All mirror in RTL through Ant Design's direction.
 */
export function AppShell({
  nav,
  activeKey,
  onNavigate,
  header,
  banners,
  layout = 'top',
  children,
}: AppShellProps) {
  const t = useLabel();
  const { token } = theme.useToken();
  const [collapsed, setCollapsed] = useState(false);
  const compact = layout === 'side_compact';
  const screens = Grid.useBreakpoint();
  // Phones: less padding round the page (QA BUG-07); see AppHeader for the same rule.
  const pad = screens.md === false && (screens.xs === true || screens.sm === true) ? 12 : 24;

  const items: MenuProps['items'] = nav.map((item) => {
    const text = t(item.labelKey);
    return {
      key: item.key,
      icon: item.icon,
      'data-testid': `nav-${item.key}`,
      // Icon-only menus still need a name for screen readers and a tooltip for everyone.
      title: text,
      label: item.locked ? (
        <Tooltip title={t('licence.upgrade_hint')} placement="right">
          <span>
            {text} <LockOutlined aria-label={t('licence.locked')} />
          </span>
        </Tooltip>
      ) : (
        text
      ),
      onClick: () => {
        onNavigate(item.path);
      },
    };
  });
  const selectedKeys = activeKey === undefined ? [] : [activeKey];
  // The sections offered, whatever the layout and whatever fits on screen (tests, diagnostics).
  const itemKeys = nav.map((item) => item.key).join(' ');

  // Full logo in the top bar and the wide sidebar; the square mark in the narrow ones.
  const brand = (short: boolean) => (
    <BrandLogo variant={short ? 'icon' : 'full'} height={short ? 32 : 28} />
  );

  if (layout === 'top') {
    const topNav = (
      <>
        {brand(false)}
        <nav
          aria-label={t('nav.main')}
          data-testid="nav-top"
          data-items={itemKeys}
          style={{ flex: 1, minWidth: 0, marginInlineStart: 16 }}
        >
          <Menu
            mode="horizontal"
            // Click, not hover: works with touch and keyboard, and does not open by accident.
            triggerSubMenuAction="click"
            selectedKeys={selectedKeys}
            items={items}
            style={{ borderBottom: 'none', lineHeight: '62px', background: 'transparent' }}
            overflowedIndicator={
              <span data-testid="nav-more">
                {t('nav.more')} <DownOutlined aria-hidden />
              </span>
            }
          />
        </nav>
      </>
    );
    return (
      <Layout style={{ minHeight: '100vh' }} data-layout="top">
        {typeof header === 'function' ? header(topNav) : header}
        {banners}
        <Layout.Content id="main" style={{ padding: pad, minWidth: 0 }}>
          {children}
        </Layout.Content>
      </Layout>
    );
  }

  const narrow = compact || collapsed;
  return (
    <Layout style={{ minHeight: '100vh' }} data-layout={layout}>
      <Layout.Sider
        collapsible={!compact}
        collapsed={narrow}
        onCollapse={setCollapsed}
        breakpoint={compact ? undefined : 'lg'}
        theme="light"
        width={232}
        collapsedWidth={compact ? 64 : 80}
        trigger={compact ? null : undefined}
        style={{ borderInlineEnd: `1px solid ${token.colorBorderSecondary}` }}
      >
        <div
          style={{
            padding: 16,
            minHeight: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: narrow ? 'center' : 'flex-start',
          }}
        >
          {brand(narrow)}
        </div>
        <nav
          aria-label={t('nav.main')}
          data-testid={compact ? 'nav-compact' : 'nav-side'}
          data-items={itemKeys}
        >
          <Menu mode="inline" selectedKeys={selectedKeys} items={items} />
        </nav>
      </Layout.Sider>
      {/* min-width 0: the page column may shrink below its widest table (which then scrolls
          inside its own box), so the page never scrolls sideways (QA BUG-07). */}
      <Layout style={{ minWidth: 0 }}>
        {typeof header === 'function' ? header(null) : header}
        {banners}
        <Layout.Content id="main" style={{ padding: pad, minWidth: 0 }}>
          {children}
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
