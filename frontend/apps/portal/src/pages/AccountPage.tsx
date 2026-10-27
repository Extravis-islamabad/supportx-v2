import { Space, Typography } from 'antd';

import { AccountSecurityCard, useLabel } from '@supportx/ui';

/** My account in the portal (WP-039 session 3, REQ-SEC-028): password, MFA, recent sign-ins. */
export function AccountPage() {
  const t = useLabel();
  return (
    <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 720 }}>
      <Typography.Title level={1}>{t('nav.profile')}</Typography.Title>
      <AccountSecurityCard />
    </Space>
  );
}
