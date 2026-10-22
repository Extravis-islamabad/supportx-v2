import { afterEach, describe, expect, it, vi } from 'vitest';

import { isRtlLocale, label } from './label';

describe('label', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns the English label by default', () => {
    expect(label('module.incident_management')).toBe('Incident Management');
  });

  it('returns the Arabic label for ar', () => {
    expect(label('module.incident_management', 'ar')).toBe('إدارة الحوادث');
  });

  it('falls back to English when the locale lacks the key', () => {
    expect(label('module.incident_management', 'ur')).toBe('Incident Management');
  });

  it('humanizes unknown codes and warns once', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    expect(label('UNKNOWN_STATUS_CODE')).toBe('Unknown Status Code');
    expect(label('UNKNOWN_STATUS_CODE')).toBe('Unknown Status Code');

    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('marks Arabic and Urdu as right-to-left', () => {
    expect(isRtlLocale('ar')).toBe(true);
    expect(isRtlLocale('ur')).toBe(true);
    expect(isRtlLocale('en')).toBe(false);
  });
});
