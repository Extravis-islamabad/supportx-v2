import type { AuditEntry } from '@supportx/api-client';
import { en, type LabelInput, type LabelParams } from '@supportx/labels';

import { OpenLink } from './StateTag';

type T = (key: LabelInput, params?: LabelParams) => string;

export const OUTCOME_COLOURS: Record<AuditEntry['outcome'], string> = {
  done: 'success',
  refused: 'warning',
  failed: 'error',
};

/**
 * What happened, in words. An approval decision names its outcome ("Approved a service request")
 * when the entry records one (`details.outcome`, QA9-F-03); older entries keep the general label.
 */
export function actionLabel(t: T, entry: Pick<AuditEntry, 'action' | 'details'>): string {
  const outcome = entry.details.outcome;
  if (typeof outcome === 'string') {
    const key = `audit.decision.${entry.action}.${outcome}`;
    if (key in en) return t(key);
  }
  return t(`audit.action.${entry.action}`);
}

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
      {objectText} · <OpenLink to={path}>{t('audit.ui.open')}</OpenLink>
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

// Browser and system names are product names, the same in every language; only the sentence
// around them is a label. Order matters: Edge and Opera also say "Chrome", Chrome says "Safari".
const BROWSERS: [RegExp, string][] = [
  [/SupportX\/(\d+)/, 'SupportX app'],
  [/Edg(?:e|A|iOS)?\/(\d+)/, 'Edge'],
  [/OPR\/(\d+)/, 'Opera'],
  [/(?:Firefox|FxiOS)\/(\d+)/, 'Firefox'],
  [/(?:Chrome|CriOS)\/(\d+)/, 'Chrome'],
  [/Version\/(\d+)[^ ]* (?:Mobile\/\S+ )?Safari\//, 'Safari'],
];
const SYSTEMS: [RegExp, string][] = [
  [/iPhone|iPad|iPod/, 'iOS'],
  [/Android/, 'Android'],
  [/Windows/, 'Windows'],
  [/Mac OS X|Macintosh/, 'macOS'],
  [/CrOS/, 'ChromeOS'],
  [/Linux/, 'Linux'],
];

/** A browser's own string as "Chrome 155 on macOS" (AUD-01); unknown parts said so in words. */
export function deviceLabel(t: T, userAgent: string): string {
  let browser: string | undefined;
  for (const [pattern, name] of BROWSERS) {
    const found = pattern.exec(userAgent);
    if (found !== null) {
      browser = `${name} ${found[1] ?? ''}`.trim();
      break;
    }
  }
  const system = SYSTEMS.find(([pattern]) => pattern.test(userAgent))?.[1];
  if (browser === undefined && system === undefined) return t('audit.ui.device_unknown');
  return t('audit.ui.device', {
    browser: browser ?? t('audit.ui.device_unknown_browser'),
    system: system ?? t('audit.ui.device_unknown_system'),
  });
}
