import { Layout, Typography } from 'antd';

import { AppearanceControls, useLabel } from '@supportx/ui';

/** Placeholder home page. Real technician console screens start with WP-015. */
export function HomePage() {
  const t = useLabel();

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Content style={{ padding: 48 }}>
        <Typography.Title>{t('product.name')}</Typography.Title>
        <Typography.Paragraph type="secondary">{t('app.console.name')}</Typography.Paragraph>
        <AppearanceControls />
      </Layout.Content>
    </Layout>
  );
}
