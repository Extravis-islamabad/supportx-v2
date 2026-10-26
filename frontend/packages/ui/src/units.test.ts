import { theme } from 'antd';
import { describe, expect, it } from 'vitest';

import { ApiError } from '@supportx/api-client';
import { problem } from '@supportx/api-client/testing';
import { label } from '@supportx/labels';

import { describeError } from './errors/describe';
import { visibleNav, type NavItem } from './shell/nav';
import { buildTheme, darken, DEFAULT_BRANDING, lighten } from './theme';

const t = (key: string, params?: Record<string, unknown>) => label(key, 'en', params as never);

describe('theme', () => {
  it('uses the SupportX purple by default and lets a tenant override it', () => {
    expect(DEFAULT_BRANDING.colorPrimary).toBe('#7e40d1');
    expect(buildTheme('light').token?.colorPrimary).toBe('#7e40d1');
    expect(buildTheme('dark', { colorPrimary: '#0055aa' }).token?.colorPrimary).toBe('#0055aa');
    expect(buildTheme('dark').algorithm).toBe(theme.darkAlgorithm);
  });

  it('high contrast: black text and borders, thicker lines, darker primary', () => {
    const contrast = buildTheme('high_contrast');
    expect(contrast.token?.colorText).toBe('#000000');
    expect(contrast.token?.colorBorder).toBe('#000000');
    expect(contrast.token?.lineWidth).toBe(2);
    expect(contrast.token?.colorPrimary).toBe(darken('#7e40d1', 0.35));
    expect(darken('#ffffff', 0.5)).toBe('#808080');
    expect(lighten('#000000', 0.5)).toBe('#808080');
  });

  it.each(['#7e40d1', '#9619B5', '#0055aa', '#1677ff', '#b80000'])(
    'dark (%s): selected menu and tab text reaches WCAG AA on the selected and page backgrounds',
    (colorPrimary) => {
      const config = buildTheme('dark', { colorPrimary });
      const token = theme.getDesignToken(config);
      const selected = config.components?.Menu?.itemSelectedColor;
      expect(config.components?.Tabs?.itemSelectedColor).toBe(selected);
      expect(config.components?.Menu?.horizontalItemSelectedColor).toBe(selected);
      for (const background of [token.colorPrimaryBg, '#141414']) {
        expect(contrastRatio(String(selected), background)).toBeGreaterThanOrEqual(4.5);
      }
    },
  );
});

/** WCAG 2.1 contrast ratio of two opaque #rrggbb colours. */
function contrastRatio(a: string, b: string): number {
  const luminance = (hex: string) => {
    const value = Number.parseInt(hex.slice(1, 7), 16);
    const [r, g, b] = [value >> 16, (value >> 8) & 0xff, value & 0xff].map((channel) => {
      const c = channel / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    }) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (high + 0.05) / (low + 0.05);
}

describe('visibleNav', () => {
  const items: NavItem[] = [
    { key: 'home', path: '/', labelKey: 'nav.home' },
    {
      key: 'requests',
      path: '/requests',
      labelKey: 'nav.requests',
      feature: 'incident',
      permissions: ['requests.view'],
    },
    {
      key: 'cmdb',
      path: '/cmdb',
      labelKey: 'nav.cmdb',
      feature: 'cmdb',
      permissions: ['cmdb.view'],
    },
    {
      key: 'admin',
      path: '/admin',
      labelKey: 'nav.admin',
      permissions: ['roles.view', 'users.manage'],
    },
  ];
  const has = (feature: string) => feature !== 'cmdb';

  it('shows only sections whose permission the user holds', () => {
    const requester = (keys: readonly string[]) => keys.includes('requests.view');
    expect(
      visibleNav(items, { canAny: requester, has, managesLicence: false }).map((i) => i.key),
    ).toEqual(['home', 'requests']);
  });

  it('shows the admin area for any admin permission', () => {
    const manager = (keys: readonly string[]) => keys.includes('users.manage');
    expect(
      visibleNav(items, { canAny: manager, has, managesLicence: false }).map((i) => i.key),
    ).toEqual(['home', 'admin']);
  });

  it('shows sections outside the plan locked to whoever manages the licence', () => {
    const everything = () => true;
    const nav = visibleNav(items, { canAny: everything, has, managesLicence: true });
    expect(nav.map((i) => [i.key, i.locked])).toEqual([
      ['home', false],
      ['requests', false],
      ['cmdb', true],
      ['admin', false],
    ]);
    expect(
      visibleNav(items, { canAny: everything, has, managesLicence: false }).map((i) => i.key),
    ).not.toContain('cmdb');
  });
});

describe('describeError', () => {
  it('explains entitlement problems with the feature and the reason', () => {
    const feature = describeError(
      new ApiError(
        403,
        problem(403, 'entitlement_required', { params: { feature: 'cmdb' } }),
        null,
      ),
      t,
    );
    expect(feature.title).toBe('Your plan does not include this feature.');
    expect(feature.detail).toBe(
      'Configuration Management Database is not part of your organisation’s plan.',
    );
    expect(feature.reference).toBe('req-0001');

    const readOnly = describeError(
      new ApiError(403, problem(403, 'read_only_mode', { params: { reason: 'expired' } }), null),
      t,
    );
    expect(readOnly.title).toMatch(/read-only mode/);
    expect(readOnly.detail).toBe('The licence or subscription has expired.');

    const seats = describeError(
      new ApiError(403, problem(403, 'technician_limit_reached'), null),
      t,
    );
    expect(seats.title).toMatch(/technician seats/);
  });

  it('never shows a code, JSON or a stack for unknown errors', () => {
    expect(describeError(new Error('TypeError: x is undefined'), t)).toEqual({
      title: 'Something went wrong on our side. Please try again.',
      reference: null,
    });
    expect(describeError(new ApiError(0, null, 'r1', 'network'), t).title).toMatch(
      /cannot be reached/,
    );
  });
});

describe('C2: fonts per language', () => {
  it('C2: Arabic never falls back to the tall Nastaliq face; Urdu gets taller lines', () => {
    const arabic = String(buildTheme('light', {}, 'ar').token?.fontFamily);
    expect(arabic).not.toMatch(/Nastaliq|Nastaleeq/);
    expect(arabic).toMatch(/Naskh|Geeza|Noto Sans Arabic/);
    const urdu = buildTheme('dark', {}, 'ur').token;
    expect(String(urdu?.fontFamily)).toContain('Noto Nastaliq Urdu');
    expect(urdu?.lineHeight).toBeGreaterThan(1.8);
    expect(buildTheme('high_contrast', {}, 'ar').token?.fontFamily).toBe(arabic);
  });
});
