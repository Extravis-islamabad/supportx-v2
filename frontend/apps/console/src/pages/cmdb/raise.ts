import type { RaiseKind } from '../assets/raise';

/** The work-item kinds a CI raises, each with the right its create form needs (WP-053 S5c). */
export const CI_RAISE_KINDS: readonly (readonly [RaiseKind, string])[] = [
  ['incident', 'incidents.create'],
  ['service_request', 'requests.create'],
  ['change', 'changes.create'],
];

/**
 * The create form's address for a raise from a CI (REQ-CMDB-019 AC1): the template (a request's
 * catalogue item) and `ci=`, which lane A's create forms link once the CI is known (#638).
 */
export function ciRaisePath(kind: RaiseKind, template: string, ciId: string): string {
  const params = new URLSearchParams();
  params.set(kind === 'service_request' ? 'item' : 'template', template);
  params.set('ci', ciId);
  const base = {
    incident: '/incidents/new',
    service_request: '/requests/new',
    change: '/changes/new',
  };
  return `${base[kind]}?${params.toString()}`;
}
