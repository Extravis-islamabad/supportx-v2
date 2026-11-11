import {
  calendarKeys,
  releaseCalendarKeys,
  useChangeCalendar,
  useReleaseCalendar,
  useReleaseChanges,
} from '@supportx/api-client';

import type { ScheduleKind } from './ScheduleCalendar';

// The staged types on the shared calendar (WP-045c S3, WP-058b S1): each one's planned stage
// (the server's PLANNED_STAGE), its query and its wording. Each calendar shows the other on
// "Show …" (REQ-REL-038).

/** No records of the other type are linked to a change on the calendar (yet). */
const noLinks = (): string[] | undefined => undefined;

/** A release's changes, by ID (REQ-REL-039: its scheduler shows only those by default). */
function useReleaseChangeIds(id: string): string[] | undefined {
  return useReleaseChanges(id).data?.map((c) => c.id);
}

export const CHANGES: ScheduleKind = {
  type: 'changes',
  stage: 'implementation',
  useEntries: useChangeCalendar,
  useLinked: noLinks,
  queryKey: calendarKeys.all,
  preview: true, // the re-approval preview before a move (ADR-042 §5)
  title: 'changes.calendar.title',
  list: 'changes.calendar.list',
  notMoved: 'changes.calendar.not_moved',
  showOther: 'changes.calendar.show_releases',
  testId: 'change-calendar',
};

export const RELEASES: ScheduleKind = {
  type: 'releases',
  stage: 'deployment',
  useEntries: useReleaseCalendar,
  useLinked: useReleaseChangeIds,
  queryKey: releaseCalendarKeys.all,
  preview: false, // a release has no re-approval preview; the server's schedule guard decides
  title: 'releases.calendar.title',
  list: 'releases.calendar.list',
  notMoved: 'releases.calendar.not_moved',
  showOther: 'releases.calendar.show_changes',
  testId: 'release-calendar',
};
