import { LockOutlined } from '@ant-design/icons';
import { Layout, Menu, Tooltip, Typography, theme } from 'antd';
import { useState, type ReactNode } from 'react';

import { useAppearance, useLabel } from '../appearance';
import type { VisibleNavItem } from './nav';

export interface AppShellProps {
  nav: VisibleNavItem[];
  /** Key of the section being shown. */
  activeKey: string | undefined;
  onNavigate: (path: string) => void;
  header: ReactNode;
  /** Licence and connectivity banners, above the page. */
  banners?: ReactNode;
  children: ReactNode;
}

/** Console layout: collapsible sidebar (mirrors in RTL), header, banners, page. */
export function AppShell({ nav, activeKey, onNavigate, header, banners, children }: AppShellProps) {
  const t = useLabel();
  const { token } = theme.useToken();
  const { branding } = useAppearance();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        breakpoint="lg"
        theme="light"
        width={232}
        style={{ borderInlineEnd: `1px solid ${token.colorBorderSecondary}` }}
      >
        <div style={{ padding: 16, minHeight: 64, display: 'flex', alignItems: 'center' }}>
          {branding.logoUrl !== undefined ? (
            <img src={branding.logoUrl} alt={t('product.name')} style={{ maxHeight: 32 }} />
          ) : (
            <Typography.Text strong style={{ color: token.colorPrimary, fontSize: 18 }}>
              {collapsed ? t('product.short_name') : t('product.name')}
            </Typography.Text>
          )}
        </div>
        <nav aria-label={t('nav.main')}>
          <Menu
            mode="inline"
            selectedKeys={activeKey === undefined ? [] : [activeKey]}
            items={nav.map((item) => ({
              key: item.key,
              icon: item.icon,
              'data-testid': `nav-${item.key}`,
              label: item.locked ? (
                <Tooltip title={t('licence.upgrade_hint')} placement="right">
                  <span>
                    {t(item.labelKey)} <LockOutlined aria-label={t('licence.locked')} />
                  </span>
                </Tooltip>
              ) : (
                t(item.labelKey)
              ),
              onClick: () => {
                onNavigate(item.path);
              },
            }))}
          />
        </nav>
      </Layout.Sider>
      <Layout>
        {header}
        {banners}
        <Layout.Content id="main" style={{ padding: 24 }}>
          {children}
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
