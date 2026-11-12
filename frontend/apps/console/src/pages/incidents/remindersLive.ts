import { useQueryClient } from '@tanstack/react-query';

import { usePersonalChannel } from '@supportx/realtime';

// Your reminders change live on your personal channel only (WP-046a S2, REQ-INC-082 AC2).

export const ALERT_CHOICES = [0, 15, 60, 1440] as const;
export const MY_REMINDERS_CHANGED = 'work_items.my_reminders_changed';

/** Your reminders refetch when your personal channel says one changed. */
export function useRemindersLive() {
  const queryClient = useQueryClient();
  usePersonalChannel((event) => {
    if (event.type === MY_REMINDERS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: ['reminders'] });
    }
  });
}
