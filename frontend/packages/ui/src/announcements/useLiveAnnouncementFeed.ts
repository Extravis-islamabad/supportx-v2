import { useQueryClient } from '@tanstack/react-query';

import { queryKeys, useAnnouncementFeed } from '@supportx/api-client';
import { usePersonalChannel, useTenantChannel } from '@supportx/realtime';

import { useRefetchAfter } from './useRefetchAfter';

/** The tenant-wide signal sent when something published changed (no IDs, see the backend). */
export const FEED_CHANGED = 'announcements.feed_changed';
/** The person's own dismissals and follows changed (on their personal channel). */
export const PERSONAL_CHANGED = 'announcements.personal_changed';

/**
 * Keeps the user's feed (what is live for them) current with no reload (WP-012):
 * - the tenant-wide "announcements changed" signal (no IDs) refetches it; the API filters;
 * - the feed says how many seconds until its content changes by the clock (a scheduled start or
 *   an end), and a timer refetches then. Relative seconds, so a wrong client clock does not
 *   matter.
 */
export function useLiveAnnouncementFeed(enabled = true) {
  const queryClient = useQueryClient();
  const feed = useAnnouncementFeed(enabled);
  useTenantChannel((message) => {
    if (message.type === FEED_CHANGED || message.type === 'refresh') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.announcements.feed });
    }
  });
  // My own dismissals and follows from another device (WP-032 D7): on my channel only.
  usePersonalChannel((message) => {
    if (message.type === PERSONAL_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.announcements.feed });
    }
  });
  useRefetchAfter(feed.data?.next_change_in_seconds, feed.dataUpdatedAt, () => {
    void feed.refetch();
  });
  return feed;
}
