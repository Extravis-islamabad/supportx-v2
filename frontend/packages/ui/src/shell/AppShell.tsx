import { DownOutlined, LockOutlined, MenuOutlined } from '@ant-design/icons';
import { Button, ConfigProvider, Drawer, Grid, Layout, Menu, Tooltip, type MenuProps } from 'antd';
import { useContext, useState, type ReactNode } from 'react';

import type { NavLayout } from '@supportx/api-client';

import { useLabel } from '../appearance';
import { BrandLogo } from '../brand';
import { SHELL } from '../theme';
import type { VisibleNavItem } from './nav';

export interface AppShellProps {
  nav: VisibleNavItem[];
  /** Key of the section being shown. */
  activeKey: string | undefined;
  onNavigate: (path: string) => void;
  /**
   * The header. With the top-bar layout the navigation lives inside the header row: the shell
   * passes it in (`topNav`), and the header places it after the brand. On phones the shell passes
   * the menu button that opens the navigation drawer (`menu`), for the start of the row.
   */
  header: ReactNode | ((topNav: ReactNode, menu?: ReactNode) => ReactNode);
  /** Licence and connectivity banners, above the page. */
  banners?: ReactNode;
  /**
   * Where the navigation sits (the user's preference, stored server-side). Default: the side bar
   * with labels (D-124).
   */
  layout?: NavLayout;
  children: ReactNode;
}

/**
 * Console layout in three variants (a per-user choice), with the same white top bar and the same
 * page in all three (UI pass 2, docs/design/target):
 * - `side`: a dark indigo sidebar with icons and labels (the default), collapsible.
 * - `side_compact`: a narrow dark rail with icons only (labels as tooltips and accessible names).
 * - `top`: the dark menu as a band under the top bar, a "More" menu for what does not fit; the
 *   page keeps the full width (tables).
 * Menu items are the same in all three (permission- and licence-driven, see `visibleNav`).
 * All mirror in RTL through Ant Design's direction.
 *
 * Below the phone breakpoint (`md`) every layout gives way to a drawer behind a menu button in the
 * top bar, so the page gets the whole width (QA 2026-11-05 V2: a permanent 64 px rail took 15%).
 */
export function AppShell({
  nav,
  activeKey,
  onNavigate,
  header,
  banners,
  layout = 'side',
  children,
}: AppShellProps) {
  const t = useLabel();
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const compact = layout === 'side_compact';
  const screens = Grid.useBreakpoint();
  const { direction } = useContext(ConfigProvider.ConfigContext);
  // Phones, as AppHeader decides them: measured below `md` with `xs` or `sm` matched. Before the
  // first measurement (and where no media queries exist) the desktop layout stays.
  const phone = screens.md === false && (screens.xs === true || screens.sm === true);
  // Phones: less padding round the page (QA BUG-07).
  const pad = phone ? 12 : 24;

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
        setDrawer(false);
        onNavigate(item.path);
      },
    };
  });
  const selectedKeys = activeKey === undefined ? [] : [activeKey];
  // The sections offered, whatever the layout and whatever fits on screen (tests, diagnostics).
  const itemKeys = nav.map((item) => item.key).join(' ');

  // Full logo in the wide navigation; the square mark in the narrow ones. Always on the dark
  // navigation, so always the white-text logo.
  const brand = (short: boolean) => (
    <BrandLogo variant={short ? 'icon' : 'full'} height={short ? 32 : 28} surface="dark" />
  );

  if (phone) {
    const menu = (
      <Button
        type="text"
        icon={<MenuOutlined />}
        aria-label={t('nav.open_menu')}
        aria-expanded={drawer}
        aria-controls="nav-drawer"
        onClick={() => {
          setDrawer(true);
        }}
        data-testid="nav-menu-button"
      />
    );
    return (
      <Layout style={{ minHeight: '100vh' }} data-layout={layout} data-phone="true">
        {typeof header === 'function' ? header(null, menu) : header}
        <Drawer
          open={drawer}
          onClose={() => {
            setDrawer(false);
          }}
          // The start side: left, or right when the page reads right to left.
          placement={direction === 'rtl' ? 'right' : 'left'}
          width={280}
          title={brand(false)}
          closable
          forceRender // the navigation is in the page even while closed (tests, screen readers)
          styles={{
            header: { background: SHELL.navBg, borderBottom: 'none' },
            body: { padding: 0, background: SHELL.navBg },
          }}
          rootClassName="nav-drawer"
          id="nav-drawer"
        >
          <nav aria-label={t('nav.main')} data-testid="nav-drawer" data-items={itemKeys}>
            <Menu mode="inline" theme="dark" selectedKeys={selectedKeys} items={items} />
          </nav>
        </Drawer>
        {banners}
        <Layout.Content id="main" style={{ padding: pad, minWidth: 0 }}>
          {children}
        </Layout.Content>
      </Layout>
    );
  }

  if (layout === 'top') {
    return (
      <Layout style={{ minHeight: '100vh' }} data-layout="top">
        {typeof header === 'function' ? header(null) : header}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            paddingInline: pad,
            background: SHELL.navBg,
            minWidth: 0,
          }}
        >
          {brand(false)}
          <nav
            aria-label={t('nav.main')}
            data-testid="nav-top"
            data-items={itemKeys}
            // The menu's own "More" stays inside the band; its submenu opens in a popup.
            style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}
          >
            <Menu
              mode="horizontal"
              theme="dark"
              // Click, not hover: works with touch and keyboard, and does not open by accident.
              triggerSubMenuAction="click"
              selectedKeys={selectedKeys}
              items={items}
              style={{ borderBottom: 'none', lineHeight: '48px', background: 'transparent' }}
              overflowedIndicator={
                <span data-testid="nav-more">
                  {t('nav.more')} <DownOutlined aria-hidden />
                </span>
              }
            />
          </nav>
        </div>
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
        theme="dark"
        width={220}
        collapsedWidth={64}
        trigger={compact ? null : undefined}
        // The dark navigation runs the full height however long the page (UI pass 2).
        style={{ position: 'sticky', top: 0, height: '100vh', overflowY: 'auto' }}
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
          <Menu mode="inline" theme="dark" selectedKeys={selectedKeys} items={items} />
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
