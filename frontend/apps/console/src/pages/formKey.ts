import { useLocation, useNavigate } from 'react-router';

// One Idempotency-Key per form visit, kept across a remount (QA-2026-11-11 F-01).
//
// A key made with useMemo dies with the component: if the page remounts while a create is in
// flight (a banner, a session refetch), the form comes back with a fresh key, and a second click
// makes a duplicate. Here the key belongs to the browser's history entry (`location.key`): the
// same visit keeps it, so a repeat returns the record already made. Once the create succeeds the
// key is dropped, so coming back to the form (Back) starts a new record, never a replay.
// Callers navigate from the awaited result (`mutateAsync`), which still arrives after a remount,
// unlike `mutate`'s own callbacks.

const keys = new Map<string, string>();

/** The form visit's key, and what to do once its record is made. */
export function useFormKey(scope: string): {
  key: string;
  done: (path: string, options?: { replace?: boolean }) => void;
} {
  const location = useLocation();
  const navigate = useNavigate();
  const id = `${scope}:${location.key}`;
  let key = keys.get(id);
  if (key === undefined) {
    key = crypto.randomUUID();
    keys.set(id, key);
  }
  return {
    key,
    done: (path, options) => {
      keys.delete(id);
      void navigate(path, options);
    },
  };
}
