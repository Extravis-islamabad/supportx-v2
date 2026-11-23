import { describe, expect, it } from 'vitest';

// QA 2026-11-12 F-01: a bulk job's records never reach list channels one by one, so every screen
// that starts or shows a bulk job must follow the job's batch refresh through `useBulkRefresh`
// (one shared hook). A new bulk screen without it fails here.

const sources = import.meta.glob<string>('./**/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
});

describe('bulk jobs keep their screens live', () => {
  const bulkScreens = Object.entries(sources).filter(
    // The work item engine's drawer (assets run their own jobs, with per-record events).
    ([path, text]) =>
      !path.includes('.test.') &&
      text.includes('<BulkProgress') &&
      /from '\.{1,2}\/(incidents\/)?list\/bulk'/.test(text),
  );

  it('finds the bulk screens', () => {
    const paths = bulkScreens.map(([path]) => path).sort();
    expect(paths).toEqual(
      expect.arrayContaining([
        './changes/ChangesPage.tsx',
        './incidents/IncidentsPage.tsx',
        './problems/FollowUp.tsx',
        './releases/ReleasesPage.tsx',
      ]),
    );
  });

  it.each(bulkScreens.map(([path, text]) => [path, text] as const))(
    '%s follows its bulk jobs with useBulkRefresh',
    (_path, text) => {
      expect(text).toMatch(/useBulkRefresh\('(incident|change|release|problem|service_request)'/);
    },
  );
});
