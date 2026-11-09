import type { CSSProperties } from 'react';

/**
 * The column a portal form page sits in (QA6-PRT-02): centred in the page at a width that
 * reads well, so a wide screen keeps no large empty area at one side.
 */
export const FORM_COLUMN: CSSProperties = { width: '100%', maxWidth: 800, marginInline: 'auto' };
