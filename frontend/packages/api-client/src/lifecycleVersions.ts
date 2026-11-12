import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';

// Life cycle versions of an action-based type (ADR-049; WP-046a S4). Every write sends If-Match
// with the type's settings version the screen showed (`settings_version` of the list) and the
// list is refetched after it; other screens follow through `work_items.settings_changed`.
export type LifecycleVersions = components['schemas']['LifecycleVersionsOut'];
export type LifecycleVersion = components['schemas']['LifecycleVersionOut'];
export type LifecycleMove = components['schemas']['LifecycleMoveIO'];
export type LifecycleProblem = components['schemas']['LifecycleProblemOut'];
export type LifecycleDraft = components['schemas']['LifecycleDraftOut'];

/** The types whose life cycles are action-based (staged types version with their stages). */
export type LifecycleBase = 'incidents' | 'requests' | 'problems';
type Path = `/api/v1/incidents/settings/lifecycles${string}`;
// The incident paths stand for every base in the typed client: same shapes under each path.
const at = <P extends Path>(base: LifecycleBase, path: P): P =>
  path.replace('/api/v1/incidents', `/api/v1/${base}`) as P;
const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export const lifecycleKeys = {
  all: (base: LifecycleBase) => ['lifecycle_versions', base] as const,
  versions: (base: LifecycleBase, lifecycle: string) =>
    ['lifecycle_versions', base, lifecycle] as const,
  moves: (base: LifecycleBase, lifecycle: string, number: number) =>
    ['lifecycle_versions', base, lifecycle, 'moves', number] as const,
};

/** A life cycle's versions, the newest first, and the one new records start on. */
export function useLifecycleVersions(base: LifecycleBase, lifecycle: string, enabled = true) {
  return useQuery({
    queryKey: lifecycleKeys.versions(base, lifecycle),
    queryFn: () =>
      call(
        api.GET(at(base, '/api/v1/incidents/settings/lifecycles/{lifecycle}/versions'), {
          params: { path: { lifecycle } },
        }),
      ),
    enabled,
  });
}

/** One version's moves (a draft's as last saved). */
export function useLifecycleMoves(
  base: LifecycleBase,
  lifecycle: string,
  number: number | undefined,
) {
  return useQuery({
    queryKey: lifecycleKeys.moves(base, lifecycle, number ?? 0),
    queryFn: () =>
      call(
        api.GET(
          at(base, '/api/v1/incidents/settings/lifecycles/{lifecycle}/versions/{number}/moves'),
          { params: { path: { lifecycle, number: number ?? 0 } } },
        ),
      ),
    enabled: number !== undefined,
  });
}

/** One change of a life cycle's versions. */
export type LifecycleChange =
  | { kind: 'start' }
  | { kind: 'save'; moves: LifecycleMove[] }
  | { kind: 'publish' }
  | { kind: 'discard' }
  | { kind: 'retire'; number: number };

async function send(
  base: LifecycleBase,
  lifecycle: string,
  change: LifecycleChange,
  version: number,
): Promise<unknown> {
  const header = ifMatch(version);
  const path = { lifecycle };
  switch (change.kind) {
    case 'start':
      return call(
        api.POST(at(base, '/api/v1/incidents/settings/lifecycles/{lifecycle}/versions'), {
          params: { header, path },
        }),
      );
    case 'save':
      return call(
        api.PUT(at(base, '/api/v1/incidents/settings/lifecycles/{lifecycle}/draft/moves'), {
          params: { header, path },
          body: { moves: change.moves },
        }),
      );
    case 'publish':
      return call(
        api.POST(at(base, '/api/v1/incidents/settings/lifecycles/{lifecycle}/draft/publish'), {
          params: { header, path },
        }),
      );
    case 'discard':
      return call(
        api.DELETE(at(base, '/api/v1/incidents/settings/lifecycles/{lifecycle}/draft'), {
          params: { header, path },
        }),
      );
    case 'retire':
      return call(
        api.POST(
          at(base, '/api/v1/incidents/settings/lifecycles/{lifecycle}/versions/{number}/retire'),
          { params: { header, path: { lifecycle, number: change.number } } },
        ),
      );
  }
}

/** Change a life cycle's versions; `version` is the settings version the screen showed. */
export function useLifecycleChange(base: LifecycleBase, lifecycle: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ change, version }: { change: LifecycleChange; version: number }) =>
      send(base, lifecycle, change, version),
    // Errors are shown where the change was made (the card or the dialog), never as a toast.
    meta: { silent: true },
    onSettled: () => queryClient.invalidateQueries({ queryKey: lifecycleKeys.all(base) }),
  });
}
