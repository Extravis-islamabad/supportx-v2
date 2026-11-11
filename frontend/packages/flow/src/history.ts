// Undo and redo for the designer (REQ-WF-008 AC2: every edit, at least 50 steps back). Pure:
// each edit pushes the state it leaves; undo and redo move along the list. A new edit after
// an undo drops what was undone, as every editor does.

export const HISTORY_LIMIT = 100;

export interface History<T> {
  past: T[];
  present: T;
  future: T[];
}

export function startHistory<T>(present: T): History<T> {
  return { past: [], present, future: [] };
}

/** An edit: the present moves to the past (the oldest step goes once over the limit). */
export function record<T>(history: History<T>, next: T, limit = HISTORY_LIMIT): History<T> {
  if (Object.is(next, history.present)) return history;
  const past = [...history.past, history.present];
  return {
    past: past.length > limit ? past.slice(past.length - limit) : past,
    present: next,
    future: [],
  };
}

export function undo<T>(history: History<T>): History<T> {
  const previous = history.past[history.past.length - 1];
  if (previous === undefined) return history;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
  };
}

export function redo<T>(history: History<T>): History<T> {
  const [next, ...rest] = history.future;
  if (next === undefined) return history;
  return { past: [...history.past, history.present], present: next, future: rest };
}

/** The present replaced without a step (a save's new version, another admin's change). */
export function reset<T>(present: T): History<T> {
  return startHistory(present);
}

export const canUndo = (history: History<unknown>): boolean => history.past.length > 0;
export const canRedo = (history: History<unknown>): boolean => history.future.length > 0;
