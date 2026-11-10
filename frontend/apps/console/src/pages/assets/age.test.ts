import { describe, expect, it } from 'vitest';

import { ageBetween, basisDay } from './age';

// The backend's cases (test_assets_domain.py test_age_in_years_months_and_days), so both agree.
describe('ageBetween', () => {
  it('counts whole years, months and days', () => {
    expect(ageBetween('2025-09-02', '2026-11-05')).toEqual({ years: 1, months: 2, days: 3 });
    expect(ageBetween('2026-01-31', '2026-03-01')).toEqual({ years: 0, months: 1, days: 1 });
    expect(ageBetween('2026-11-05', '2026-11-05')).toEqual({ years: 0, months: 0, days: 0 });
    expect(ageBetween('2027-01-01', '2026-11-05')).toBeNull();
  });

  it('takes the basis the tenant chose; no basis date means unknown', () => {
    const asset = { acquired_on: null, created_at: '2026-01-02T08:00:00Z' };
    expect(basisDay('acquisition_date', asset)).toBeNull();
    expect(basisDay('created_date', asset)).toBe('2026-01-02');
  });

  it("counts the creation day where the viewer is, as today is (not the timestamp's UTC date)", () => {
    // 21:30 UTC is already the next day east of UTC: the day must follow the viewer's clock.
    const late = { acquired_on: null, created_at: '2026-01-02T21:30:00Z' };
    const local = new Date(late.created_at);
    const day = [local.getFullYear(), local.getMonth() + 1, local.getDate()]
      .map((part) => String(part).padStart(2, '0'))
      .join('-');
    expect(basisDay('created_date', late)).toBe(day);
  });
});
