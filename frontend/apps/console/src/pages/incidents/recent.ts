/**
 * Incidents this user opened lately, newest first (REQ-INC-085: pickers and quick search offer
 * them before anything is typed). Kept per user in this browser, like the last record tab
 * (D-081): a convenience, so storage errors simply mean "nothing recent". The server still
 * checks each ID against the user's scope when it is shown.
 */
export const RECENT_MAX = 10;

const key = (userId: string) => `sx.incident.recent.${userId}`;

export function recentIncidents(userId: string | null | undefined): string[] {
  if (userId == null) return [];
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(key(userId)) ?? '[]');
    return Array.isArray(stored)
      ? stored.filter((id): id is string => typeof id === 'string').slice(0, RECENT_MAX)
      : [];
  } catch {
    return [];
  }
}

export function rememberIncident(userId: string | null | undefined, id: string): void {
  if (userId == null) return;
  const next = [id, ...recentIncidents(userId).filter((other) => other !== id)].slice(
    0,
    RECENT_MAX,
  );
  try {
    localStorage.setItem(key(userId), JSON.stringify(next));
  } catch {
    // storage unavailable: nothing is offered as recent, search still works
  }
}
