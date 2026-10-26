import { describe, expect, it } from 'vitest';

import { ar } from './resources/ar';

// QA C1 (WP-020b): the Arabic hand-over texts are read with "{{id}}" = "هذه الحادثة" (this
// incident, feminine) as well as an ID such as INC-70. They must not use a masculine verb or
// masculine pronouns for the incident.
describe('C1: Arabic hand-over wording', () => {
  it('C1: no masculine verb or pronoun for the incident', () => {
    const texts = [
      ar['incidents.handover_moves'],
      ar['incidents.handover_following_text'],
      ar['incidents.handover_text'],
      ar['incidents.handed_over_following'],
    ].join(' ');
    for (const masculine of ['سينتقل', 'متابعته', 'فتحه', 'تحديثاته', 'تغييره', 'بشأنه']) {
      // Whole words only: the feminine forms (فتحها) start with the same letters.
      expect(texts).not.toMatch(new RegExp(`${masculine}(?![\\u0621-\\u064A])`));
    }
    expect(ar['incidents.handover_moves']).toContain('سيتم نقل');
  });
});
