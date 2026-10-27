import { Flex, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { useLabel } from '@supportx/ui';

import { InvitationsCard } from './InvitationsCard';
import { MfaPolicyCard } from './MfaPolicyCard';
import { PasswordPolicyCard } from './PasswordPolicyCard';
import { SessionsCard } from './SessionsCard';
import { SsoCard } from './SsoCard';

/**
 * Admin › Sign-in and security (WP-039, REQ-SEC-017): every sign-in setting in SupportX itself,
 * never in Keycloak's console. Changes another admin makes show here without a reload.
 */
export function SecurityPage() {
  const t = useLabel();
  const queryClient = useQueryClient();
  const refetch = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.identity.all });
  };
  useListChannel('identity', refetch);
  useListChannel('invitations', refetch);
  return (
    <Flex vertical gap={16} data-testid="admin-security">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t('security.intro')}
      </Typography.Paragraph>
      <SsoCard />
      <PasswordPolicyCard />
      <MfaPolicyCard />
      <InvitationsCard />
      <SessionsCard />
    </Flex>
  );
}
