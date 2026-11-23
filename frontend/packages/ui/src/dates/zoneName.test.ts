import { describe, expect, it } from 'vitest';

import { zoneName } from './time';

// QA-2026-11-11 F-10: the time-zone note names the zone in the reader's language.

describe('zoneName', () => {
  it('is the zone’s name in the reader’s language, never its code', () => {
    expect(zoneName('Asia/Karachi', 'en')).not.toBe('Asia/Karachi');
    expect(zoneName('Asia/Karachi', 'en')).toMatch(/Pakistan/);
    const arabic = zoneName('Asia/Karachi', 'ar');
    expect(arabic).not.toBe('Asia/Karachi');
    expect(arabic).toMatch(/[؀-ۿ]/);
  });

  it('is the code itself when the zone is unknown', () => {
    expect(zoneName('Not/AZone', 'en')).toBe('Not/AZone');
  });
});
