/**
 * The record page opens on the tab this user used last, Conversation the first time (D-081).
 * Kept per user in this browser: a convenience, so storage errors (private mode, blocked
 * storage) simply mean "start on Conversation".
 */
export const RECORD_TABS = ['conversation', 'details', 'history', 'automation'] as const;
export type RecordTab = (typeof RECORD_TABS)[number];
export const DEFAULT_TAB: RecordTab = 'conversation';

const key = (userId: string) => `sx.incident.tab.${userId}`;

export function lastTab(userId: string | null): RecordTab {
  if (userId === null) return DEFAULT_TAB;
  try {
    const stored = localStorage.getItem(key(userId));
    return (RECORD_TABS as readonly string[]).includes(stored ?? '')
      ? (stored as RecordTab)
      : DEFAULT_TAB;
  } catch {
    return DEFAULT_TAB;
  }
}

export function rememberTab(userId: string | null, tab: string): void {
  if (userId === null || !(RECORD_TABS as readonly string[]).includes(tab)) return;
  try {
    localStorage.setItem(key(userId), tab);
  } catch {
    // storage unavailable: the page still works, it just starts on Conversation next time
  }
}
