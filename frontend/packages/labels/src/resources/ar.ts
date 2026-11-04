import { ar as shared } from './shared/ar.ts';
import { ar as ai } from './ai/ar.ts';
import { ar as analytics } from './analytics/ar.ts';
import { ar as announcements } from './announcements/ar.ts';
import { ar as audit } from './audit/ar.ts';
import { ar as automation } from './automation/ar.ts';
import { ar as errors } from './errors/ar.ts';
import { ar as files } from './files/ar.ts';
import { ar as identityAccess } from './identity_access/ar.ts';
import { ar as integrations } from './integrations/ar.ts';
import { ar as knowledge } from './knowledge/ar.ts';
import { ar as licensing } from './licensing/ar.ts';
import { ar as metadata } from './metadata/ar.ts';
import { ar as notifications } from './notifications/ar.ts';
import { ar as organization } from './organization/ar.ts';
import { ar as sla } from './sla/ar.ts';
import { ar as workItems } from './work_items/ar.ts';
import type { LabelResource } from './en';

// Arabic is mandatory from day one (D-006). Missing keys fall back to English.
// Each module keeps its labels in <module>/ar.ts (README.md).
export const ar: LabelResource = {
  ...shared,
  ...ai,
  ...analytics,
  ...announcements,
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
};

export const arByModule = {
  shared,
  ai,
  analytics,
  announcements,
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
