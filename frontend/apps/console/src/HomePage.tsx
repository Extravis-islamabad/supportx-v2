import { Layout, Space, Typography } from 'antd';

import { AppearanceControls, useLabel } from '@supportx/ui';

import { ApiStatus } from './ApiStatus';

/** Placeholder home page. Real technician console screens start with WP-015. */
export function HomePage() {
  const t = useLabel();

  return (
    <Layout.Content style={{ padding: 48 }}>
      <Typography.Title>{t('product.name')}</Typography.Title>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Text type="secondary">{t('app.console.name')}</Typography.Text>
        <ApiStatus />
      </Space>
      <AppearanceControls />
    </Layout.Content>
  );
}
