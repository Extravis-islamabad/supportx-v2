import { useMatches } from 'react-router';

import type { LabelKey } from '@supportx/labels';
import { ComingSoon } from '@supportx/ui';

export function ComingSoonPage() {
  const handle = useMatches().at(-1)?.handle as { titleKey?: LabelKey } | undefined;
  return <ComingSoon titleKey={handle?.titleKey ?? 'product.name'} />;
}
