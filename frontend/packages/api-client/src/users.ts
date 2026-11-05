import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';

import { api, call, rememberEtag } from './client';
import { ApiError } from './errors';
import { clearPending, setPending, settlePendingAfterError } from './pendingPreferences';
import { queryKeys } from './keys';
import type { components } from './schema';
import type { MeResponse } from './session';

export type UserDetail = components['schemas']['UserDetail'];
export type UserPage = components['schemas']['UserPage'];
export type UserPreferencesPatch = components['schemas']['UserPreferencesPatch'];
export type NavLayout = components['schemas']['NavLayout'];
export type FormDensity = components['schemas']['FormDensity'];
export type ThemeMode = components['schemas']['ThemeMode'];

/** Personal preferences a person may leave to the default (WP-042; null: the default). */
export type PersonalPreference =
  | 'theme_mode'
  | 'text_scale'
  | 'week_start'
  | 'date_format'
  | 'time_format'
  | 'digits'
  | 'urdu_script';
export type PersonalPreferenceChange = {
  [K in PersonalPreference]: { field: K; value: NonNullable<MeResponse['user'][K]> | null };
}[PersonalPreference];
export type FilterExpression = components['schemas']['FilterExpression'];
export type FilterCondition = components['schemas']['FilterCondition'];

/** List parameters the UI controls; `filter` is the shared JSON filter DSL (architecture.md §6.5). */
export interface UsersQuery {
  filter?: FilterExpression;
  /** Search names and emails: word starts, Arabic and Urdu spellings, typos (WP-027). */
  q?: string;
  /** e.g. `display_name` or `-last_login_at` */
  sort?: string;
  limit?: number;
}

/** Free-text search as a filter DSL expression over name and email. */
export function searchFilter(text: string): FilterExpression | undefined {
  const value = text.trim();
  if (value === '') return undefined;
  return {
    or: [
      { field: 'display_name', op: 'contains', value },
      { field: 'email', op: 'contains', value },
    ],
  };
}

/** AND the non-empty parts together (undefined when there is nothing to filter on). */
export function allOf(...parts: (FilterExpression | undefined)[]): FilterExpression | undefined {
  const present = parts.filter((part): part is FilterExpression => part !== undefined);
  if (present.length === 0) return undefined;
  return present.length === 1 ? present[0] : { and: present };
}

/** GET /users with cursor pagination: `fetchNextPage()` follows `next_cursor`. */
export function useUsers(query: UsersQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.users.list(query),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/users', {
          params: {
            query: {
              filter: query.filter === undefined ? undefined : JSON.stringify(query.filter),
              q: query.q === undefined || query.q.trim() === '' ? undefined : query.q.trim(),
              sort: query.sort,
              limit: query.limit ?? 50,
              cursor: pageParam ?? undefined,
              include_total: pageParam === null,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

/** GET /users/{id}, for code that needs one person once (e.g. a form filling its defaults). */
export function fetchUser(id: string): Promise<UserDetail> {
  return call(api.GET('/api/v1/users/{user_id}', { params: { path: { user_id: id } } }));
}

/** One user; its ETag is remembered by the client for the next PATCH (If-Match). */
export function useUser(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.users.detail(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/users/{user_id}', { params: { path: { user_id: id ?? '' } } })),
    enabled: id !== undefined,
  });
}

/**
 * PATCH /users/{id} (own signature / time zone). Sends If-Match for the version the form was
 * loaded from, so a concurrent change answers 409 `version_conflict` instead of being lost.
 */
export function useUpdateUser(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    // The form shows these errors itself (inline, conflict dialog), so no global toast.
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: UserPreferencesPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/users/{user_id}', {
          params: { path: { user_id: id }, header: { 'If-Match': `"${String(version)}"` } },
          body: changes,
        }),
      ),
    onSuccess: (user) => {
      rememberEtag(`/api/v1/users/${id}`, `"${String(user.version)}"`);
      queryClient.setQueryData(queryKeys.users.detail(id), user);
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.users.all, 'list'] });
    },
  });
}

type UserPatch = components['schemas']['UserPreferencesPatch'];

// One person's preference saves, one after another (QA 2026-11-05 V3). Each save reads the
// record's version and sends If-Match; two at once (the start-up resends, or a quick language and
// layout change) read the same version and the second got a 409, shown as "someone else saved
// this". A save sends only its own field, so after a 409 it is safe to read the version again and
// send the same field once more. Other fields anyone else changed are kept; the same field
// changed meanwhile (on another device) is replaced by this save, which is fine for one's own
// preference. Only version_conflict is retried, and only here: never on shared records.
const queues = new Map<string, Promise<unknown>>();
const RETRIES = 2;

export function saveOwnPreference(
  queryClient: QueryClient,
  userId: string,
  body: UserPatch,
): Promise<UserDetail> {
  const send = async (): Promise<UserDetail> => {
    for (let attempt = 0; ; attempt += 1) {
      const latest = await queryClient.query({
        queryKey: queryKeys.users.detail(userId),
        queryFn: () =>
          call(api.GET('/api/v1/users/{user_id}', { params: { path: { user_id: userId } } })),
        staleTime: 0,
      });
      try {
        return await call(
          api.PATCH('/api/v1/users/{user_id}', {
            params: {
              path: { user_id: userId },
              header: { 'If-Match': `"${String(latest.version)}"` },
            },
            body,
          }),
        );
      } catch (error) {
        if (
          !(error instanceof ApiError && error.code === 'version_conflict') ||
          attempt >= RETRIES
        ) {
          throw error;
        }
      }
    }
  };
  const next = (queues.get(userId) ?? Promise.resolve()).then(send, send);
  queues.set(
    userId,
    next.catch(() => undefined),
  );
  return next;
}

/**
 * Change the signed-in user's navigation layout (WP-011). Stored server-side, so it follows the
 * user to other devices (their sessions refresh live). Applied at once (optimistic); reads the
 * current version just before saving, so it never collides with an open profile form.
 */
export function useSetNavLayout(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (layout: NavLayout) => {
      return saveOwnPreference(queryClient, userId, { nav_layout: layout });
    },
    onMutate: (layout) => {
      setPending(userId, 'nav_layout', layout);
      queryClient.setQueryData<MeResponse | null>(queryKeys.session, (me) =>
        me ? { ...me, user: { ...me.user, nav_layout: layout } } : me,
      );
    },
    onSuccess: (user, value) => {
      clearPending(userId, 'nav_layout', value);
      rememberEtag(`/api/v1/users/${userId}`, `"${String(user.version)}"`);
      queryClient.setQueryData(queryKeys.users.detail(userId), user);
    },
    onError: (error, value) => {
      settlePendingAfterError(userId, 'nav_layout', value, error);
      void queryClient.invalidateQueries({ queryKey: queryKeys.session }); // undo the optimism
    },
  });
}

/**
 * Change the signed-in user's record form layout (WP-020c): comfortable (one column, labels
 * above) or compact (two columns, labels on the left). Stored with the user like the navigation
 * layout; applied at once (optimistic).
 */
export function useSetFormDensity(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (density: FormDensity) => {
      return saveOwnPreference(queryClient, userId, { form_density: density });
    },
    onMutate: (density) => {
      setPending(userId, 'form_density', density);
      queryClient.setQueryData<MeResponse | null>(queryKeys.session, (me) =>
        me ? { ...me, user: { ...me.user, form_density: density } } : me,
      );
    },
    onSuccess: (user, value) => {
      clearPending(userId, 'form_density', value);
      rememberEtag(`/api/v1/users/${userId}`, `"${String(user.version)}"`);
      queryClient.setQueryData(queryKeys.users.detail(userId), user);
    },
    onError: (error, value) => {
      settlePendingAfterError(userId, 'form_density', value, error);
      void queryClient.invalidateQueries({ queryKey: queryKeys.session });
    },
  });
}

/**
 * Change the signed-in user's UI language (QA BUG-04). Stored with the user (not in this
 * browser), so it survives reloads and follows them to other devices; `null` goes back to the
 * identity provider's locale. Applied at once (optimistic), like the navigation layout.
 */
export function useSetUiLocale(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (locale: 'en' | 'ar' | 'ur' | null) => {
      return saveOwnPreference(queryClient, userId, { ui_locale: locale });
    },
    onMutate: (locale) => {
      setPending(userId, 'ui_locale', locale);
      if (locale === null) return;
      queryClient.setQueryData<MeResponse | null>(queryKeys.session, (me) =>
        me ? { ...me, user: { ...me.user, locale } } : me,
      );
    },
    onSuccess: (user, value) => {
      clearPending(userId, 'ui_locale', value);
      rememberEtag(`/api/v1/users/${userId}`, `"${String(user.version)}"`);
      queryClient.setQueryData(queryKeys.users.detail(userId), user);
      void queryClient.invalidateQueries({ queryKey: queryKeys.session });
    },
    onError: (error, value) => {
      settlePendingAfterError(userId, 'ui_locale', value, error);
      void queryClient.invalidateQueries({ queryKey: queryKeys.session });
    },
  });
}

/**
 * Change one personal preference (WP-042; REQ-ADM-058, 059, 062): theme, text size, week start,
 * date or time format. `null` clears it, so the site's or tenant's default applies again (read
 * by the server, never copied onto the person). Applied at once (optimistic) like the layout;
 * the session is read again afterwards for the default a cleared choice falls back to.
 */
export function useSetPreference(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ field, value }: PersonalPreferenceChange) => {
      return saveOwnPreference(queryClient, userId, { [field]: value });
    },
    onMutate: ({ field, value }) => {
      setPending(userId, field, value);
      if (value === null) return; // the default comes back with the session
      queryClient.setQueryData<MeResponse | null>(queryKeys.session, (me) =>
        me ? { ...me, user: { ...me.user, [field]: value } } : me,
      );
    },
    onSuccess: (user, { field, value }) => {
      clearPending(userId, field, value);
      rememberEtag(`/api/v1/users/${userId}`, `"${String(user.version)}"`);
      queryClient.setQueryData(queryKeys.users.detail(userId), user);
      void queryClient.invalidateQueries({ queryKey: queryKeys.session });
    },
    onError: (error, { field, value }) => {
      settlePendingAfterError(userId, field, value, error);
      void queryClient.invalidateQueries({ queryKey: queryKeys.session });
    },
  });
}
