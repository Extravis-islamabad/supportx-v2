import { CHANGES, RELEASES } from '../staged/kinds';
import { ScheduleCalendar } from '../staged/ScheduleCalendar';

// The change calendar (WP-045c S3): the shared staged calendar on changes' implementation
// window, with the re-approval preview before a move (ADR-042 §5); releases on "Show releases".
export function ChangeCalendarPage() {
  return <ScheduleCalendar kind={CHANGES} other={RELEASES} />;
}
