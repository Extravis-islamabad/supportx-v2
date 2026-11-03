import { ur as shared } from './shared/ur.ts';
import { ur as analytics } from './analytics/ur.ts';
import { ur as announcements } from './announcements/ur.ts';
import { ur as audit } from './audit/ur.ts';
import { ur as automation } from './automation/ur.ts';
import { ur as errors } from './errors/ur.ts';
import { ur as files } from './files/ur.ts';
import { ur as identityAccess } from './identity_access/ur.ts';
import { ur as integrations } from './integrations/ur.ts';
import { ur as knowledge } from './knowledge/ur.ts';
import { ur as licensing } from './licensing/ur.ts';
import { ur as metadata } from './metadata/ur.ts';
import { ur as notifications } from './notifications/ur.ts';
import { ur as organization } from './organization/ur.ts';
import { ur as sla } from './sla/ur.ts';
import { ur as workItems } from './work_items/ur.ts';
import type { LabelResource } from './en';

// Urdu: mandatory from Stage 2 (D-006). Missing keys fall back to English.
// Each module keeps its labels in <module>/ur.ts (README.md).
export const ur: LabelResource = {
  ...shared,
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

export const urByModule = {
  shared,
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
