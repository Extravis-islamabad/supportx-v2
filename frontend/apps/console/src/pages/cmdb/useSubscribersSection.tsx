import { useCiSubscribers, type Ci } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

import { SubscribersSection } from './Subscribers';

/** The section only for a business service; nothing for any other CI. */
export function useSubscribersSection(ci: Ci) {
  const t = useLabel();
  const found = useCiSubscribers(ci.id);
  if (found.data?.business_service !== true) return null;
  return {
    key: 'subscribers',
    title: t('cmdb.section.subscribers'),
    children: <SubscribersSection ci={ci} found={found.data} />,
  };
}
