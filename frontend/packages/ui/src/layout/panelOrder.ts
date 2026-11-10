import type { PanelSection } from './RecordPage';

/**
 * The panel's order rule (V-13, the coordinator 2026-11-10): Properties comes first among the
 * carded sections, as on the incident; who asked belongs inside it, not in a card above it.
 * Bare sections (the AI summary) may lead. Returns the sections that break it, for a dev warning.
 */
export function sectionsBeforeProperties(sections: PanelSection[]): string[] {
  const at = sections.findIndex((section) => section.key === 'properties');
  if (at < 0) return [];
  return sections
    .slice(0, at)
    .filter((section) => section.bare !== true)
    .map((section) => section.key);
}

// Vite's flag, read without its types (packages/ui has none): true in dev builds only.
export const DEV = (import.meta as { env?: { DEV?: boolean } }).env?.DEV === true;
