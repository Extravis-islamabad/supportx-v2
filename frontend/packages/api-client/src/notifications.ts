import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Notifications (WP-023): the centre (your own entries), your preferences, the rules per event
// (admins), the mail-waiting status (admins) and a record's delivery log (staff). Live updates
// arrive on your personal channel (`notifications.created`, `notifications.read`,
// `notifications.preferences_changed`) and on the record's channel
// (`notifications.delivery_recorded`); `useNotificationsLive` in the console applies them.
export type NotificationEntry = components['schemas']['NotificationOut'];
export type NotificationCentre = components['schemas']['NotificationCentreOut'];
export type NotificationPreferences = components['schemas']['NotificationPreferencesOut'];
export type NotificationChoice = components['schemas']['NotificationChoiceOut'];
export type NotificationCategory = components['schemas']['NotificationCategory'];
export type NotificationChannel = components['schemas']['NotificationChannel'];
export type NotificationRule = components['schemas']['NotificationRuleOut'];
export type NotificationRuleInput = components['schemas']['NotificationRuleIn'];
export type NotificationCondition = components['schemas']['NotificationCondition'];
export type NotificationStatus = components['schemas']['NotificationStatusOut'];
export type NotificationDelivery = components['schemas']['NotificationDeliveryOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });
const PAGE = 30;

/** Your notification centre, newest first, a page at a time; `unread` is on every page. */
export function useNotifications(enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.notifications.centre,
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/notifications', {
          params: { query: { limit: PAGE, ...(pageParam ? { cursor: pageParam } : {}) } },
        }),
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled,
    meta: { silent: true },
  });
}

/** Mark entries read (`ids` left out: all of them). The badge updates from the answer. */
export function useMarkNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (ids: string[] | undefined) =>
      call(api.POST('/api/v1/notifications/read', { body: ids ? { ids } : {} })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.centre });
    },
  });
}

export function useNotificationPreferences() {
  return useQuery({
    queryKey: queryKeys.notifications.preferences,
    queryFn: () => call(api.GET('/api/v1/notifications/preferences')),
  });
}

/** Save your preferences (If-Match: the version read, 0 before the first save). */
export function useSaveNotificationPreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      off,
      doNotDisturb,
      version,
    }: {
      off: { category: NotificationCategory; channel: NotificationChannel }[];
      doNotDisturb: boolean;
      version: number;
    }) =>
      call(
        api.PUT('/api/v1/notifications/preferences', {
          params: { header: ifMatch(version) },
          body: { off, do_not_disturb: doNotDisturb },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.notifications.preferences, saved);
    },
  });
}

/** Every event with its rule (admins). */
export function useNotificationRules(enabled = true) {
  return useQuery({
    queryKey: queryKeys.notifications.rules,
    queryFn: () => call(api.GET('/api/v1/notifications/rules')),
    enabled,
  });
}

function useRulesChanged() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.rules });
  };
}

/** Save an event's rule (If-Match: its version, 0 while the default applies). */
export function useSaveNotificationRule() {
  const changed = useRulesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      eventCode,
      rule,
      version,
    }: {
      eventCode: string;
      rule: NotificationRuleInput;
      version: number;
    }) =>
      call(
        api.PUT('/api/v1/notifications/rules/{event_code}', {
          params: { path: { event_code: eventCode }, header: ifMatch(version) },
          body: rule,
        }),
      ),
    onSuccess: changed,
  });
}

/** Back to the shipped default. */
export function useResetNotificationRule() {
  const changed = useRulesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ eventCode, version }: { eventCode: string; version: number }) =>
      call(
        api.DELETE('/api/v1/notifications/rules/{event_code}', {
          params: { path: { event_code: eventCode }, header: ifMatch(version) },
        }),
      ),
    onSuccess: changed,
  });
}

/** E-mails waiting because outgoing mail is not set up (admins' banner). */
export function useNotificationStatus(enabled = true) {
  return useQuery({
    queryKey: queryKeys.notifications.status,
    queryFn: () => call(api.GET('/api/v1/notifications/status')),
    enabled,
    refetchInterval: 60_000,
    meta: { silent: true },
  });
}

/**
 * A record's notifications: to whom, how, when, and whether they went (REQ-INC-134). For the
 * record page's history (lane A); refresh it on the record channel's
 * `notifications.delivery_recorded`.
 */
export function useRecordDeliveries(recordType: string, recordId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.notifications.deliveries(recordType, recordId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/notifications/deliveries', {
          params: { query: { record_type: recordType, record_id: recordId ?? '' } },
        }),
      ),
    enabled: recordId !== undefined,
  });
}
