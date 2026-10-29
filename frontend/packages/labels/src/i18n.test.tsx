import { act, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FSI, label, PDI } from './label';
import { LabelsProvider } from './react';
import { useLabels } from './useLabels';

describe('i18next labels', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('interpolates parameters', () => {
    expect(label('auth.tenant_switched', 'en', { tenant: 'Other Company' })).toBe(
      'You are now working in Other Company.',
    );
    // A Latin value in an Arabic sentence is isolated (the isolation rule, isolation-cases.json).
    expect(label('auth.tenant_switched', 'ar', { tenant: 'Other Company' })).toBe(
      `أنت تعمل الآن في ${FSI}Other Company${PDI}.`,
    );
  });

  it('does not HTML-escape values (React escapes on render)', () => {
    expect(label('errors.reference_is', 'en', { reference: '<a&b>' })).toBe('Reference: <a&b>');
  });

  it('picks English plural forms', () => {
    expect(label('users.total', 'en', { count: 1 })).toBe('1 user');
    expect(label('users.total', 'en', { count: 7 })).toBe('7 users');
  });

  it('picks the six Arabic plural forms', () => {
    const ar = (count: number) => label('users.total', 'ar', { count });
    expect(ar(0)).toBe('لا يوجد مستخدمون');
    expect(ar(1)).toBe('مستخدم واحد');
    expect(ar(2)).toBe('مستخدمان');
    expect(ar(5)).toBe('5 مستخدمين');
    expect(ar(11)).toBe('11 مستخدمًا');
    expect(ar(100)).toBe('100 مستخدم');
  });

  it('falls back to English for a key Urdu lacks, then to humanize() with a warning', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(label('users.title', 'ur')).toBe('Users');
    expect(label('some_module.awaiting_parts', 'ar')).toBe('Awaiting Parts');
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('re-renders components when the language changes', () => {
    function Probe() {
      const t = useLabels();
      return <span>{t('actions.save')}</span>;
    }
    function Harness() {
      const [locale, setLocale] = useState<'en' | 'ar'>('en');
      return (
        <LabelsProvider locale={locale}>
          <Probe />
          <button
            onClick={() => {
              setLocale('ar');
            }}
          >
            switch
          </button>
        </LabelsProvider>
      );
    }
    render(<Harness />);
    expect(screen.getByText('Save')).toBeDefined();
    act(() => {
      screen.getByRole('button').click();
    });
    expect(screen.getByText('حفظ')).toBeDefined();
  });
});
