import { CHANGES, RELEASES } from '../staged/kinds';
import { ScheduleCalendar } from '../staged/ScheduleCalendar';

// The release calendar (WP-058b S1; REQ-REL-038): the shared staged calendar on releases'
// deployment window, changes on "Show changes". With `?focus=<id>` it is the release's
// scheduler (REQ-REL-039): opened on its deployment, its own changes shown.
export function ReleaseCalendarPage() {
  return <ScheduleCalendar kind={RELEASES} other={CHANGES} />;
}
