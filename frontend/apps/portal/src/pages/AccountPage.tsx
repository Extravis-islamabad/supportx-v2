import { Space, Typography } from 'antd';

import {
  AccountSecurityCard,
  ContactDetailsCard,
  SignedInSessionsCard,
  useLabel,
} from '@supportx/ui';

import { FORM_COLUMN } from './formColumn';

/**
 * My account in the portal: contact details (WP-028, REQ-PRT-013) and security (WP-039 session 3,
 * REQ-SEC-028: password, MFA, recent sign-ins).
 */
export function AccountPage() {
  const t = useLabel();
  return (
    <Space direction="vertical" size="large" style={FORM_COLUMN}>
      <Typography.Title level={1}>{t('nav.profile')}</Typography.Title>
      <ContactDetailsCard />
      <AccountSecurityCard />
      <SignedInSessionsCard />
    </Space>
  );
}
