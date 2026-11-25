import { Flex, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@supportx/api-client';
import { refreshQueries, useListChannel } from '@supportx/realtime';
import { useLabel } from '@supportx/ui';

import { DomainsCard } from './DomainsCard';
import { InvitationsCard } from './InvitationsCard';
import { MfaPolicyCard } from './MfaPolicyCard';
import { NetworkRulesCard } from './NetworkRulesCard';
import { SiteNetworksCard } from './SiteNetworksCard';
import { PasswordPolicyCard } from './PasswordPolicyCard';
import { SecurityOverview } from './SecurityOverview';
import { MobileAppCard } from './MobileAppCard';
import { SessionsCard } from './SessionsCard';
import { SsoCard } from './SsoCard';
import { SsoPolicyCard } from './SsoPolicyCard';
import { VendorSupportCard } from './VendorSupportCard';
import { vendorSupportKeys } from '@supportx/api-client';

/**
 * Admin › Sign-in and security (WP-039, REQ-SEC-017): every sign-in setting in SupportX itself,
 * never in Keycloak's console. Changes another admin makes show here without a reload.
 */
export function SecurityPage() {
  const t = useLabel();
  const queryClient = useQueryClient();
  const refetch = () => {
    refreshQueries(queryClient, queryKeys.identity.all);
  };
  // Every message refreshes what it covers; a refresh is covered by the hook itself.
  useListChannel(
    'identity',
    (m) => {
      if (m.covered === true) return;
      refetch();
      // A vendor support grant changed (WP-057 S4c-3): its list and the open grant's drawer.
      refreshQueries(queryClient, vendorSupportKeys.all);
    },
    { covers: [queryKeys.identity.all, vendorSupportKeys.all] },
  );
  useListChannel(
    'invitations',
    (m) => {
      if (m.covered !== true) refetch();
    },
    { covers: [queryKeys.identity.all] },
  );
  // Keys and service accounts change on the people channel: the overview counts them (S4d).
  useListChannel(
    'users',
    (m) => {
      if (m.covered !== true) refreshQueries(queryClient, queryKeys.identity.overview);
    },
    { covers: [queryKeys.identity.overview] },
  );
  return (
    <Flex vertical gap={16} data-testid="admin-security">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t('security.intro')}
      </Typography.Paragraph>
      <SecurityOverview />
      <SsoCard />
      <DomainsCard />
      <SsoPolicyCard />
      <PasswordPolicyCard />
      <MfaPolicyCard />
      <InvitationsCard />
      <SessionsCard />
      <MobileAppCard />
      <NetworkRulesCard />
      <SiteNetworksCard />
      <VendorSupportCard />
    </Flex>
  );
}
