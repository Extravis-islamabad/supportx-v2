import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import {
  ApiError,
  keptDraftKeys,
  useDiscardKeptDraft,
  useKeptDraftOnServer,
  useSaveKeptDraft,
  type KeptDraftForm,
} from '@supportx/api-client';
import type { FieldValues, UseFormReturn } from '@supportx/forms';
import { usePersonalChannel } from '@supportx/realtime';

const SAVE_AFTER_MS = 3000;
const BACKOFF_MAX_MS = 5 * 60_000;

/**
 * The server copy of an unsent create form (WP-046a S5c; REQ-INC-019), next to the tab's own copy
 * (`useKeptDraft`). Lane C's conditions: an inline note (role status, no focus taken) above the
 * first field; restoring over typing asks first; Discard forgets both copies; the time in the
 * person's zone and format; an unreadable draft offers Discard only; a missing key shows nothing
 * and is tried again later; no "saved" chatter.
 *
 * Saving waits while a kept draft is still undecided, so new typing never replaces it unseen.
 */
export function useServerDraft<T extends FieldValues>(
  form: UseFormReturn<T>,
  formKey: KeptDraftForm,
  { localRestored }: { localRestored: boolean },
) {
  const queryClient = useQueryClient();
  const kept = useKeptDraftOnServer(formKey);
  const save = useSaveKeptDraft(formKey);
  const discard = useDiscardKeptDraft(formKey);
  const [decided, setDecided] = useState(false);
  const version = useRef(0);
  const backoff = useRef(0);
  const blockedUntil = useRef(0);
  const { watch } = form;
  const saveRef = useRef(save);
  const formRef = useRef(form);
  const refetchRef = useRef(kept.refetch);
  const latest = useRef<Record<string, unknown> | null>(null);
  const typed = useRef(false); // the person has changed a field since the form opened

  // The newest objects each render, read through refs: the save timer below depends on none of
  // them, so a re-render never restarts it (lane C's #495 review).
  useEffect(() => {
    saveRef.current = save;
    formRef.current = form;
    refetchRef.current = kept.refetch;
  });
  useEffect(() => {
    if (kept.data != null) version.current = kept.data.version;
  }, [kept.data]);
  // The tab's own copy came back: that is this work; the server copy needs no question.
  const pending = !decided && !localRestored && kept.data != null;
  const loading = kept.isLoading;

  // Another tab of the same person kept or discarded: read the version again.
  usePersonalChannel((event) => {
    if (event.type === 'work_items.draft_changed' && event.ids.includes(formKey)) {
      void queryClient.invalidateQueries({ queryKey: keptDraftKeys.one(formKey) });
    }
  });

  useEffect(() => {
    if (pending || loading) return;
    let typing: number | undefined;
    let retry: number | undefined;
    let live = true; // false once this effect is cleaned up: a late reply starts nothing
    // `again`: this try follows a 409; a second 409 waits for more typing (no ping-pong).
    const attempt = (again = false) => {
      if (!live) return;
      const values = latest.current;
      if (values === null) return;
      const wait = blockedUntil.current - Date.now();
      if (wait > 0) {
        // Backing off: one try when the wait is over, even if nothing is typed meanwhile.
        window.clearTimeout(retry);
        retry = window.setTimeout(() => {
          attempt(again);
        }, wait);
        return;
      }
      saveRef.current.mutate(
        { values, version: version.current },
        {
          onSuccess: (saved) => {
            version.current = saved.version;
            backoff.current = 0;
            if (latest.current === values) latest.current = null; // saved: nothing waits
          },
          onError: (error: unknown) => {
            if (error instanceof ApiError && error.status === 409) {
              if (again) return;
              // Another tab saved first: take its version, then save this tab's typing over it
              // once (lane C's #495 note); if its draft now waits for a decision, this effect
              // has been cleaned up and nothing is saved.
              void refetchRef.current().then((read) => {
                if (read.isSuccess) version.current = read.data?.version ?? 0; // null: none kept
                attempt(true);
              });
              return;
            }
            // No key (503) or no connection: quiet, and tried again later, ever more slowly.
            backoff.current = Math.min(
              BACKOFF_MAX_MS,
              backoff.current === 0 ? SAVE_AFTER_MS * 2 : backoff.current * 2,
            );
            blockedUntil.current = Date.now() + backoff.current;
            window.clearTimeout(retry);
            retry = window.setTimeout(() => {
              attempt();
            }, backoff.current);
          },
        },
      );
    };
    const subscription = watch((values, { type }) => {
      // Only the person's own typing is kept: a template, a rule or a restore sets values too
      // (no event type), and opening the form must keep nothing (matrix 43474443928).
      if (type === 'change') typed.current = true;
      if (!typed.current) return;
      window.clearTimeout(typing);
      typing = window.setTimeout(() => {
        // An untouched form (just opened, or reset after a save) keeps nothing.
        const defaults = formRef.current.formState.defaultValues;
        if (JSON.stringify(values) === JSON.stringify(defaults)) return;
        latest.current = values;
        attempt();
      }, SAVE_AFTER_MS);
    });
    return () => {
      live = false;
      window.clearTimeout(typing);
      window.clearTimeout(retry);
      subscription.unsubscribe();
    };
  }, [pending, loading, watch]);

  return {
    /** The kept draft waiting for a decision, or null. */
    pending: pending ? kept.data : null,
    restored: () => {
      setDecided(true);
    },
    discard: (onLocal: () => void) => {
      setDecided(true);
      version.current = 0;
      onLocal();
      discard.mutate();
    },
  };
}
