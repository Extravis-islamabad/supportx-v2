import { useQuery } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-040: Admin › Integrations (integrations.view). Read-only here: each kind says whether the
// caller may set it up and why not. The page refetches on `integrations.connectors_changed`
// and `integrations.mailboxes_changed` from the tenant channel.

export type ConnectorKind = components['schemas']['ConnectorKindOut'];
export type ConnectorInstance = components['schemas']['ConnectorInstanceOut'];

/** Every kind of connector with its instances and their health. */
export function useConnectorCatalogue(enabled = true) {
  return useQuery({
    queryKey: queryKeys.connectors.catalogue,
    queryFn: () => call(api.GET('/api/v1/integrations/catalogue')),
    enabled,
  });
}
