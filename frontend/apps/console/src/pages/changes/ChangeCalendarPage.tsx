import { calendarKeys, useChangeCalendar } from '@supportx/api-client';

import { ScheduleCalendar, type ScheduleKind } from '../staged/ScheduleCalendar';

// The change calendar (WP-045c S3): the shared staged calendar on changes' implementation
// window, with the re-approval preview before a move (ADR-042 §5).
const CHANGES: ScheduleKind = {
  type: 'changes',
  stage: 'implementation',
  useEntries: useChangeCalendar,
  queryKey: calendarKeys.all,
  preview: true,
  title: 'changes.calendar.title',
  list: 'changes.calendar.list',
  notMoved: 'changes.calendar.not_moved',
  testId: 'change-calendar',
};

export function ChangeCalendarPage() {
  return <ScheduleCalendar kind={CHANGES} />;
}
