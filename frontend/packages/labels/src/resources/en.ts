import { en as shared } from './shared/en.ts';
import { en as ai } from './ai/en.ts';
import { en as analytics } from './analytics/en.ts';
import { en as announcements } from './announcements/en.ts';
import { en as assets } from './assets/en.ts';
import { en as audit } from './audit/en.ts';
import { en as automation } from './automation/en.ts';
import { en as errors } from './errors/en.ts';
import { en as files } from './files/en.ts';
import { en as identityAccess } from './identity_access/en.ts';
import { en as integrations } from './integrations/en.ts';
import { en as knowledge } from './knowledge/en.ts';
import { en as licensing } from './licensing/en.ts';
import { en as metadata } from './metadata/en.ts';
import { en as notifications } from './notifications/en.ts';
import { en as organization } from './organization/en.ts';
import { en as sla } from './sla/en.ts';
import { en as workItems } from './work_items/en.ts';

// English is the reference dictionary: every key must exist here (§9.5). Each module keeps
// its labels in <module>/en.ts (README.md); this file only joins them.
export const en = {
  ...shared,
  ...ai,
  ...analytics,
  ...announcements,
  ...assets,
  ...audit,
  ...automation,
  ...errors,
  ...files,
  ...identityAccess,
  ...integrations,
  ...knowledge,
  ...licensing,
  ...metadata,
  ...notifications,
  ...organization,
  ...sla,
  ...workItems,
} as const;

/** The module files as they are, for the duplicate and coverage checks. */
export const enByModule = {
  shared,
  ai,
  analytics,
  announcements,
  assets,
  audit,
  automation,
  errors,
  files,
  identity_access: identityAccess,
  integrations,
  knowledge,
  licensing,
  metadata,
  notifications,
  organization,
  sla,
  work_items: workItems,
};

export type LabelKey = keyof typeof en;

/**
 * Plural variants (CLDR categories). English needs `_one`/`_other`; Arabic uses all six, so its
 * resources may hold `_zero`, `_two`, `_few` and `_many` keys English does not have.
 */
export type PluralKey = `${string}_${'zero' | 'one' | 'two' | 'few' | 'many' | 'other'}`;
export type LabelResource = Partial<Record<LabelKey | PluralKey, string>>;
