import type { CSSProperties } from 'react';

/**
 * The portal's one width rule (QA6-PRT-02, QA-2026-11-11 V-06): lists, the home page and
 * records fill the layout's column (PortalLayout, 1100 px, centred); forms, a confirm page
 * and the profile sit in this narrower column, centred in it, never against one side.
 */
export const FORM_COLUMN: CSSProperties = { width: '100%', maxWidth: 800, marginInline: 'auto' };
