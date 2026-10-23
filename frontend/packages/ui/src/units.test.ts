import { theme } from 'antd';
import { describe, expect, it } from 'vitest';

import { ApiError } from '@supportx/api-client';
import { problem } from '@supportx/api-client/testing';
import { label } from '@supportx/labels';

import { describeError } from './errors/describe';
import { visibleNav, type NavItem } from './shell/nav';
import { buildTheme, darken, DEFAULT_BRANDING } from './theme';

const t = (key: string, params?: Record<string, unknown>) => label(key, 'en', params as never);

describe('theme', () => {
  it('uses the Extravis purple by default and lets a tenant override it', () => {
    expect(DEFAULT_BRANDING.colorPrimary).toBe('#9619B5');
    expect(buildTheme('light').token?.colorPrimary).toBe('#9619B5');
    expect(buildTheme('dark', { colorPrimary: '#0055aa' }).token?.colorPrimary).toBe('#0055aa');
    expect(buildTheme('dark').algorithm).toBe(theme.darkAlgorithm);
  });

  it('high contrast: black text and borders, thicker lines, darker primary', () => {
    const contrast = buildTheme('high_contrast');
    expect(contrast.token?.colorText).toBe('#000000');
    expect(contrast.token?.colorBorder).toBe('#000000');
    expect(contrast.token?.lineWidth).toBe(2);
    expect(contrast.token?.colorPrimary).toBe(darken('#9619B5', 0.35));
    expect(darken('#ffffff', 0.5)).toBe('#808080');
  });
});

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
