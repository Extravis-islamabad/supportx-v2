import { screen, waitFor } from '@testing-library/react';
import { theme } from 'antd';
import { describe, expect, it } from 'vitest';

import { fakeApi } from '@supportx/api-client/testing';

import { BrandLogo, logoFor, SUPPORTX_COLOURS, SUPPORTX_LOGOS, type BrandLogos } from './brand';
import palette from './brand/palette.json';
import { AboutDialog, AppShell } from './shell';
import { renderUi } from './test/render';
import { buildTheme, DEFAULT_BRANDING, type ThemeMode } from './theme';

const noop = () => undefined;

/** WCAG 2.1 contrast ratio of two opaque #rrggbb colours. */
function contrast(a: string, b: string): number {
  const luminance = (hex: string) => {
    const value = Number.parseInt(hex.slice(1, 7), 16);
    const [r, g, b] = [value >> 16, (value >> 8) & 0xff, value & 0xff].map((channel) => {
      const c = channel / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    }) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (high + 0.05) / (low + 0.05);
}

describe('SupportX brand colours (branding.md)', () => {
  it('come from palette.json, the one source shared with the Keycloak theme', () => {
    expect(DEFAULT_BRANDING.colorPrimary).toBe(palette.primary);
    expect(DEFAULT_BRANDING.gradient).toEqual([palette.gradient.start, palette.gradient.end]);
    expect(SUPPORTX_COLOURS.primary).toBe('#7e40d1');
  });

  it('light: white on primary and on its hover and pressed shades, primary links on white', () => {
    const token = theme.getDesignToken(buildTheme('light'));
    for (const shade of [token.colorPrimary, token.colorPrimaryHover, token.colorPrimaryActive]) {
      expect(contrast(shade, '#ffffff')).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(token.colorLink, '#ffffff')).toBeGreaterThanOrEqual(4.5);
  });

  it('dark: white on primary buttons, links and their hover on the dark backgrounds', () => {
    const token = theme.getDesignToken(buildTheme('dark'));
    for (const shade of [token.colorPrimary, token.colorPrimaryHover]) {
      expect(contrast(shade, '#ffffff')).toBeGreaterThanOrEqual(4.5);
    }
    for (const background of ['#141414', '#1f1f1f']) {
      expect(contrast(token.colorLink, background)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(token.colorLinkHover, background)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('high contrast: the primary and links reach AAA with white', () => {
    const token = theme.getDesignToken(buildTheme('high_contrast'));
    expect(contrast(token.colorPrimary, '#ffffff')).toBeGreaterThanOrEqual(7);
    expect(contrast(token.colorLink, '#ffffff')).toBeGreaterThanOrEqual(7);
  });

  it('white text stays above AA across the whole gradient', () => {
    const [start, end] = SUPPORTX_COLOURS.gradient.map((hex) => Number.parseInt(hex.slice(1), 16));
    const channel = (value: number, shift: number) => (value >> shift) & 0xff;
    for (let step = 0; step <= 32; step += 1) {
      const mixed = [16, 8, 0].map((shift) =>
        Math.round(
          channel(start ?? 0, shift) +
            ((channel(end ?? 0, shift) - channel(start ?? 0, shift)) * step) / 32,
        ),
      );
      const hex = `#${mixed.map((value) => value.toString(16).padStart(2, '0')).join('')}`;
      expect(contrast(hex, '#ffffff')).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe('logo', () => {
  it('picks the version for the theme and falls back to the light one', () => {
    expect(logoFor(SUPPORTX_LOGOS, 'light', 'full')).toBe(SUPPORTX_LOGOS.full);
    expect(logoFor(SUPPORTX_LOGOS, 'dark', 'full')).toBe(SUPPORTX_LOGOS.fullOnDark);
    expect(logoFor(SUPPORTX_LOGOS, 'high_contrast', 'full')).toBe(SUPPORTX_LOGOS.fullHighContrast);
    expect(logoFor(SUPPORTX_LOGOS, 'dark', 'icon')).toBe(SUPPORTX_LOGOS.icon);
    expect(logoFor(SUPPORTX_LOGOS, 'high_contrast', 'icon')).toBe(SUPPORTX_LOGOS.iconHighContrast);
    // A tenant logo with one file (WP-017): that file everywhere, the short name when narrow.
    const tenant: BrandLogos = { full: '/tenant.png' };
    for (const mode of ['light', 'dark', 'high_contrast'] as ThemeMode[]) {
      expect(logoFor(tenant, mode, 'full')).toBe('/tenant.png');
      expect(logoFor(tenant, mode, 'icon')).toBeUndefined();
    }
  });

  it.each(['light', 'dark', 'high_contrast'] as ThemeMode[])(
    '%s: renders the matching file with the product name as its text alternative',
    (mode) => {
      renderUi(<BrandLogo />, { mode });
      const logo = screen.getByRole('img', { name: 'SupportX' });
      expect(logo.getAttribute('src')).toBe(logoFor(SUPPORTX_LOGOS, mode, 'full'));
    },
  );

  it('top bar and wide sidebar show the full logo; the compact sidebar the icon', () => {
    const shell = (layout: 'top' | 'side' | 'side_compact') => (
      <AppShell
        nav={[]}
        activeKey={undefined}
        onNavigate={noop}
        header={(topNav) => <header>{topNav}</header>}
        layout={layout}
      >
        <p>page</p>
      </AppShell>
    );
    const { unmount } = renderUi(shell('top'));
    expect(screen.getByTestId('brand-logo-full')).toBeTruthy();
    unmount();
    const side = renderUi(shell('side'));
    expect(screen.getByTestId('brand-logo-full')).toBeTruthy();
    side.unmount();
    renderUi(shell('side_compact'));
    expect(screen.getByTestId('brand-logo-icon')).toBeTruthy();
    expect(screen.queryByTestId('brand-logo-full')).toBeNull();
  });
});

describe('about dialog', () => {
  it('shows the logo, the app and the server version', async () => {
    const fake = fakeApi({ 'GET /api/v1/health': { body: { status: 'ok', version: '0.1.0' } } });
    renderUi(<AboutDialog open onClose={noop} appName="app.console.name" />);
    await waitFor(() => {
      expect(screen.getByTestId('about-version').textContent).toBe('Version 0.1.0');
    });
    expect(screen.getByText('Technician Console')).toBeTruthy();
    expect(screen.getAllByRole('img', { name: 'SupportX' }).length).toBeGreaterThan(0);
    fake.restore();
  });

  it('says so when the version cannot be read, in the user’s language', async () => {
    const fake = fakeApi({ 'GET /api/v1/health': { status: 503 } });
    renderUi(<AboutDialog open onClose={noop} appName="app.portal.name" />, { locale: 'ar' });
    await waitFor(() => {
      expect(screen.getByTestId('about-version').textContent).toBe('إصدار الخادم غير متاح الآن.');
    });
    fake.restore();
  });
});
