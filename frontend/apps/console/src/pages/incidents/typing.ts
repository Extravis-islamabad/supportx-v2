import { useEffect, useLayoutEffect, useRef } from 'react';

import { sendTyping, type EntryKind } from '@supportx/api-client';

/** No keystroke for this long: the writer has stopped. */
export const TYPING_IDLE_MS = 4_000;
/** While someone keeps typing, "start" is sent again this often (QA BUG-04). */
export const TYPING_HEARTBEAT_MS = 3_000;
/** A receiver shows a writer this long after their last signal (a lost "stop" never sticks). */
export const TYPING_SHOWN_MS = 8_000;

type Send = (id: string, state: 'start' | 'stop', kind: EntryKind) => void;

/**
 * "Someone is writing" (REQ-WI-006 AC2). `typed()` on every change: the first one sends "start",
 * and while typing goes on "start" is repeated every TYPING_HEARTBEAT_MS, shorter than the time a
 * receiver keeps showing it, so a long note never disappears from the others' screens (QA BUG-04).
 * A pause of TYPING_IDLE_MS, `stop()` or unmounting sends "stop".
 */
export function useTypingSignal(id: string, kind: EntryKind, send: Send = sendTyping) {
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastStart = useRef<number | null>(null);
  const latest = useRef({ id, kind, send });
  useLayoutEffect(() => {
    latest.current = { id, kind, send };
  });

  const stop = () => {
    if (idle.current !== null) clearTimeout(idle.current);
    idle.current = null;
    if (lastStart.current !== null) {
      latest.current.send(latest.current.id, 'stop', latest.current.kind);
    }
    lastStart.current = null;
  };
  const typed = () => {
    const now = Date.now();
    if (lastStart.current === null || now - lastStart.current >= TYPING_HEARTBEAT_MS) {
      lastStart.current = now;
      latest.current.send(latest.current.id, 'start', latest.current.kind);
    }
    if (idle.current !== null) clearTimeout(idle.current);
    idle.current = setTimeout(stop, TYPING_IDLE_MS);
  };
  // On unmount: tell the others this person stopped (stop reads refs only).
  useEffect(
    () => () => {
      if (idle.current !== null) clearTimeout(idle.current);
      if (lastStart.current !== null) {
        latest.current.send(latest.current.id, 'stop', latest.current.kind);
      }
    },
    [],
  );
  return { typed, stop };
}
