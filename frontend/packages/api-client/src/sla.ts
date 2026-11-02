import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

export type SlaCalendar = components['schemas']['SlaCalendarOut'];
export type SlaCalendarIn = components['schemas']['SlaCalendarIn'];
export type SlaCalendarPatch = components['schemas']['SlaCalendarPatch'];
export type SlaWorkingPeriod = components['schemas']['SlaWorkingPeriod'];
export type SlaWeekPreset = components['schemas']['WeekPreset'];
export type SlaHolidayList = components['schemas']['SlaHolidayListOut'];
export type SlaHolidayListIn = components['schemas']['SlaHolidayListIn'];
export type SlaHolidayListPatch = components['schemas']['SlaHolidayListPatch'];
export type SlaHoliday = components['schemas']['SlaHolidayOut'];
export type SlaHolidayIn = components['schemas']['SlaHolidayIn'];
export type SlaHolidayPatch = components['schemas']['SlaHolidayPatch'];
export type SlaHolidayPart = components['schemas']['HolidayPart'];
export type SlaHolidayImport = components['schemas']['SlaHolidayImportOut'];
export type SlaSpecialHours = components['schemas']['SlaSpecialHoursOut'];
export type SlaSpecialHoursIn = components['schemas']['SlaSpecialHoursIn'];
export type SlaSpecialHoursPatch = components['schemas']['SlaSpecialHoursPatch'];

function ifMatch(version: number) {
  return { 'If-Match': `"${String(version)}"` };
}

/** `key`: the form's Idempotency-Key, the same for a retried save (module template §8). */
function idempotent(key: string) {
  return { 'Idempotency-Key': key };
}

/**
 * Working calendars (WP-025): around the clock and the default operating hours first. Kept live
 * by the `sla.setup.changed` tenant message (ConsoleLayout), like every SLA set-up screen.
 */
export function useSlaCalendars(enabled = true) {
  return useQuery({
    queryKey: queryKeys.sla.calendars,
    queryFn: () => call(api.GET('/api/v1/sla/calendars')),
    enabled,
  });
}

/** Holiday lists with their counts and the calendars that use them. */
export function useSlaHolidayLists(enabled = true) {
  return useQuery({
    queryKey: queryKeys.sla.holidayLists,
    queryFn: () => call(api.GET('/api/v1/sla/holiday-lists')),
    enabled,
  });
}

/** The holidays of one list that touch `year`. */
export function useSlaHolidays(listId: string | null, year: number) {
  return useQuery({
    queryKey: queryKeys.sla.holidays(listId ?? '', year),
    queryFn: () =>
      call(
        api.GET('/api/v1/sla/holiday-lists/{list_id}/holidays', {
          params: { path: { list_id: listId ?? '' }, query: { year } },
        }),
      ),
    enabled: listId !== null,
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.sla.all });
    // Sites and groups show the calendar they name.
    void queryClient.invalidateQueries({ queryKey: queryKeys.access.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.organization.all });
  };
}

/**
 * Add, change and delete calendars. Changes carry the version the editor started from (If-Match),
 * so a save made elsewhere meanwhile answers 409. Errors are shown by the editor itself.
 */
export function useSlaCalendarChange() {
  const refresh = useRefresh();
  const create = useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: SlaCalendarIn; key: string }) =>
      call(api.POST('/api/v1/sla/calendars', { body, params: { header: idempotent(key) } })),
    onSuccess: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version, body }: { id: string; version: number; body: SlaCalendarPatch }) =>
      call(
        api.PATCH('/api/v1/sla/calendars/{calendar_id}', {
          params: { path: { calendar_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/sla/calendars/{calendar_id}', {
          params: { path: { calendar_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: refresh,
  });
  return { create, update, remove };
}

/** Add, rename and delete holiday lists. */
export function useSlaHolidayListChange() {
  const refresh = useRefresh();
  const create = useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: SlaHolidayListIn; key: string }) =>
      call(api.POST('/api/v1/sla/holiday-lists', { body, params: { header: idempotent(key) } })),
    onSuccess: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: SlaHolidayListPatch;
    }) =>
      call(
        api.PATCH('/api/v1/sla/holiday-lists/{list_id}', {
          params: { path: { list_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/sla/holiday-lists/{list_id}', {
          params: { path: { list_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: refresh,
  });
  return { create, update, remove };
}

/** Add, change and remove holidays of one list; import an iCalendar file; copy a year. */
export function useSlaHolidayChange(listId: string) {
  const refresh = useRefresh();
  const path = { list_id: listId };
  const create = useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: SlaHolidayIn; key: string }) =>
      call(
        api.POST('/api/v1/sla/holiday-lists/{list_id}/holidays', {
          params: { path, header: idempotent(key) },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version, body }: { id: string; version: number; body: SlaHolidayPatch }) =>
      call(
        api.PATCH('/api/v1/sla/holiday-lists/{list_id}/holidays/{holiday_id}', {
          params: { path: { ...path, holiday_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/sla/holiday-lists/{list_id}/holidays/{holiday_id}', {
          params: { path: { ...path, holiday_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: refresh,
  });
  const importFile = useMutation({
    meta: { silent: true },
    mutationFn: ({ file, key }: { file: File; key: string }) =>
      call(
        api.POST('/api/v1/sla/holiday-lists/{list_id}/import', {
          params: { path, header: idempotent(key) },
          // The raw file is the body (no multipart), like the people import (WP-021).
          body: file as unknown as never,
          bodySerializer: (body: unknown) => body as BodyInit,
          headers: { 'Content-Type': 'text/calendar' },
        }),
      ),
    onSuccess: refresh,
  });
  const copyYear = useMutation({
    meta: { silent: true },
    mutationFn: ({ year, key }: { year: number; key: string }) =>
      call(
        api.POST('/api/v1/sla/holiday-lists/{list_id}/copy-year', {
          params: { path, header: idempotent(key) },
          body: { year },
        }),
      ),
    onSuccess: refresh,
  });
  return { create, update, remove, importFile, copyYear };
}

/** Special hours for date ranges of one calendar (Ramadan, a Friday prayer break). */
export function useSlaSpecialHoursChange(calendarId: string) {
  const refresh = useRefresh();
  const path = { calendar_id: calendarId };
  const create = useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: SlaSpecialHoursIn; key: string }) =>
      call(
        api.POST('/api/v1/sla/calendars/{calendar_id}/special-hours', {
          params: { path, header: idempotent(key) },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: SlaSpecialHoursPatch;
    }) =>
      call(
        api.PATCH('/api/v1/sla/calendars/{calendar_id}/special-hours/{special_id}', {
          params: { path: { ...path, special_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/sla/calendars/{calendar_id}/special-hours/{special_id}', {
          params: { path: { ...path, special_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: refresh,
  });
  return { create, update, remove };
}
