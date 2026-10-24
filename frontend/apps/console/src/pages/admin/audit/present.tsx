import { Link } from 'react-router';

import type { AuditEntry } from '@supportx/api-client';
import type { LabelInput, LabelParams } from '@supportx/labels';

type T = (key: LabelInput, params?: LabelParams) => string;

export const OUTCOME_COLOURS: Record<AuditEntry['outcome'], string> = {
  done: 'success',
  refused: 'warning',
  failed: 'error',
};

/** Who acted: a person's name, else the kind of actor (never an ID or a code). */
export function actorLabel(t: T, entry: AuditEntry): string {
  if (entry.actor_type === 'person') return entry.actor_name ?? t('audit.ui.erased_person');
  return t(`audit_actor_type.${entry.actor_type}`);
}

/** Where the object lives in the console, if it has a page there. */
export function objectPath(entry: Pick<AuditEntry, 'object_type' | 'object_id'>): string | null {
  if (entry.object_id === null) return null;
  switch (entry.object_type) {
    case 'incident':
      return `/incidents/${entry.object_id}`;
    case 'role':
      return `/admin/roles?role=${entry.object_id}`;
    case 'audit_entry':
      return `/admin/audit?entry=${entry.object_id}`;
    default:
      return null;
  }
}

/** The object as a label (and a link where it has a page): "Role · open", "Person: Aisha Tech". */
export function objectLabel(t: T, entry: AuditEntry) {
  if (entry.object_type === null) return null;
  const objectText = t(`audit.object.${entry.object_type}`);
  if (entry.object_name !== null) return `${objectText}: ${entry.object_name}`;
  const path = objectPath(entry);
  if (path === null) return objectText;
  return (
    <>
      {objectText} ·{' '}
      <Link
        to={path}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        {t('audit.ui.open')}
      </Link>
    </>
  );
}

/** A `permission:scope` code as "Read the audit log (all records)". */
export function grantLabel(t: T, code: string): string {
  const [permission = code, scope = 'all'] = code.split(':');
  return t('audit.ui.grant', {
    permission: t(`permission.${permission}`),
    scope: t(`scope.${scope}`),
  });
}
