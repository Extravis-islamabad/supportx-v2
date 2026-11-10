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
});
