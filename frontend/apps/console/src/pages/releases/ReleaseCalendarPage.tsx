import { releaseCalendarKeys, useReleaseCalendar } from '@supportx/api-client';

import { ScheduleCalendar, type ScheduleKind } from '../staged/ScheduleCalendar';

// The release calendar (WP-058b S1; REQ-REL-027): the shared staged calendar on releases'
// deployment window. A release has no re-approval preview; the server's schedule guard decides.
const RELEASES: ScheduleKind = {
  type: 'releases',
  stage: 'deployment',
  useEntries: useReleaseCalendar,
  queryKey: releaseCalendarKeys.all,
  preview: false,
  title: 'releases.calendar.title',
  list: 'releases.calendar.list',
  notMoved: 'releases.calendar.not_moved',
  testId: 'release-calendar',
};

export function ReleaseCalendarPage() {
  return <ScheduleCalendar kind={RELEASES} />;
}
