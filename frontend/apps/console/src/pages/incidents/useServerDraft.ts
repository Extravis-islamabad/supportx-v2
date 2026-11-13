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

  useEffect(() => {
    saveRef.current = save;
  });
  useEffect(() => {
    if (kept.data != null) version.current = kept.data.version;
  }, [kept.data]);
  // The tab's own copy came back: that is this work; the server copy needs no question.
  const pending = !decided && !localRestored && kept.data != null;

  // Another tab of the same person kept or discarded: read the version again.
  usePersonalChannel((event) => {
    if (event.type === 'work_items.draft_changed' && event.ids.includes(formKey)) {
      void queryClient.invalidateQueries({ queryKey: keptDraftKeys.one(formKey) });
    }
  });

  useEffect(() => {
    if (pending || kept.isLoading) return;
    let timer: number | undefined;
    const subscription = watch((values) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (Date.now() < blockedUntil.current) return;
        const defaults = form.formState.defaultValues;
        if (JSON.stringify(values) === JSON.stringify(defaults)) return;
        saveRef.current.mutate(
          { values: values, version: version.current },
          {
            onSuccess: (saved) => {
              version.current = saved.version;
              backoff.current = 0;
            },
            onError: (error: unknown) => {
              if (error instanceof ApiError && error.status === 409) {
                // Another tab saved first: take its version, the next pause saves again.
                void kept.refetch();
                return;
              }
              // No key (503) or no connection: quiet, and tried again later, ever more slowly.
              backoff.current = Math.min(
                BACKOFF_MAX_MS,
                backoff.current === 0 ? SAVE_AFTER_MS * 2 : backoff.current * 2,
              );
              blockedUntil.current = Date.now() + backoff.current;
            },
          },
        );
      }, SAVE_AFTER_MS);
    });
    return () => {
      window.clearTimeout(timer);
      subscription.unsubscribe();
    };
  }, [pending, kept, watch, form]);

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
