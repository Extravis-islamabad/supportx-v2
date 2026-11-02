import { useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@supportx/api-client';
import { refreshList, useListChannel, useTenantChannel } from '@supportx/realtime';

/** Everything a knowledge screen shows refetches; the API decides who sees what (no IDs). */
export function useKnowledgeLive(enabled: boolean) {
  const queryClient = useQueryClient();
  const refresh = () => {
    refreshList(queryClient, [...queryKeys.knowledge.all, 'list']);
    refreshList(queryClient, queryKeys.knowledge.topics);
    refreshList(queryClient, queryKeys.knowledge.approvals);
    // Types and settings (D-120): the editor's type picker and the settings page.
    refreshList(queryClient, queryKeys.knowledge.types);
    refreshList(queryClient, queryKeys.knowledge.settings);
  };
  useListChannel(enabled ? 'knowledge' : null, refresh);
  useTenantChannel((message) => {
    if (enabled && (message.type === 'knowledge.changed' || message.type === 'refresh')) {
      refresh();
    }
  });
}
