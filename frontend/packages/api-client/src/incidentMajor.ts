import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-046b S4 (REQ-INC-141): declare a major incident and end it, the open major incidents, and
// the team and template settings.

export type IncidentMajor = components['schemas']['IncidentMajorOut'];
export type MajorIncident = components['schemas']['MajorIncidentOut'];
export type MajorSettings = components['schemas']['MajorSettingsOut'];
export type MajorSettingsInput = components['schemas']['MajorSettingsIn'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Declare it major, or end that (`end`), with a reason (If-Match). */
export function useMajorChange(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ reason, version, end }: { reason: string; version: number; end: boolean }) =>
      end
        ? call(
            api.POST('/api/v1/incidents/{record_id}/major/end', {
              params: { path: { record_id: id }, header: ifMatch(version) },
              body: { reason },
            }),
          )
        : call(
            api.POST('/api/v1/incidents/{record_id}/major', {
              params: { path: { record_id: id }, header: ifMatch(version) },
              body: { reason },
            }),
          ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.all });
    },
  });
}

/** The open major incidents this person may see. */
export function useMajorIncidents(enabled = true) {
  return useQuery({
    queryKey: [...queryKeys.incidents.all, 'list', 'majors'],
    queryFn: () => call(api.GET('/api/v1/incidents/majors')),
    enabled,
  });
}

const SETTINGS_KEY = [...queryKeys.incidents.all, 'settings', 'major'] as const;

/** The major incident team and template (administrators). */
export function useMajorSettings(enabled = true) {
  return useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: () => call(api.GET('/api/v1/incidents/settings/major')),
    enabled,
  });
}

/** Set the team and template (If-Match on the type's settings). */
export function useUpdateMajorSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ values, version }: { values: MajorSettingsInput; version: number }) =>
      call(
        api.PUT('/api/v1/incidents/settings/major', {
          params: { header: ifMatch(version) },
          body: values,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: SETTINGS_KEY });
    },
  });
}

// WP-046b S4 (REQ-INC-129): announcements made from an incident.

export type IncidentAnnouncement = components['schemas']['IncidentAnnouncementOut'];
export type IncidentAnnounceInput = components['schemas']['IncidentAnnounceIn'];

export const incidentAnnouncementsKey = (id: string) =>
  [...queryKeys.incidents.detail(id), 'announcements'] as const;

/** The announcements made from this incident that this person may see. */
export function useIncidentAnnouncements(id: string, enabled = true) {
  return useQuery({
    queryKey: incidentAnnouncementsKey(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/incidents/{record_id}/announcements', {
          params: { path: { record_id: id } },
        }),
      ),
    enabled: enabled && id !== '',
  });
}

/** Announce from the incident; `key` is one Idempotency-Key per dialog opening (lane C). */
export function useAnnounceFromIncident(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ values, key }: { values: IncidentAnnounceInput; key: string }) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/announcements', {
          params: { path: { record_id: id }, header: { 'Idempotency-Key': key } },
          body: values,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: incidentAnnouncementsKey(id) });
    },
  });
}

/** End an announcement made from the incident (archived, with your rights there). */
export function useEndIncidentAnnouncement(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (announcementId: string) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/announcements/{announcement_id}/end', {
          params: { path: { record_id: id, announcement_id: announcementId } },
          body: {},
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: incidentAnnouncementsKey(id) });
    },
  });
}

/** Attach similar incidents to a major incident as its children: a bulk job (202), as you.
 *  `key`: one Idempotency-Key per dialog opening (lane C). */
export function useAttachChildren(id: string) {
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ childIds, key }: { childIds: string[]; key: string }) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/children/attach', {
          params: { path: { record_id: id }, header: { 'Idempotency-Key': key } },
          body: { child_ids: childIds },
        }),
      ),
  });
}
