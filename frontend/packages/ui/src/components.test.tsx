import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ApiError, reportConnectivity } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, problem } from '@supportx/api-client/testing';

import { ConnectivityBanner, ErrorBoundary, reportError } from './errors';
import { LicenceBanners, WriteButton } from './licence';
import { renderUi } from './test/render';

describe('licence banners', () => {
  afterEach(() => {
    sessionStorage.clear();
  });

  it('read-only: a persistent banner for everyone, with the reason', () => {
    const entitlements = fakeEntitlements({
      state: 'read_only',
      state_reason: 'expired',
      writable: false,
    });
    renderUi(<LicenceBanners />, { licence: { entitlements, writable: false } });
    const banner = screen.getByTestId('read-only-banner');
    expect(banner.textContent).toContain('Read-only mode: you can view and export data.');
    expect(banner.textContent).toContain('The licence or subscription has expired.');
    expect(screen.queryByRole('button', { name: /close/i })).toBeNull();
  });

  it('grace: admins get a dismissible banner with the days left; others nothing', () => {
    const entitlements = fakeEntitlements({
      state: 'grace',
      state_reason: 'expired',
      days_left: 11,
      admin_warning: true,
    });
    const { unmount } = renderUi(<LicenceBanners />, { licence: { entitlements, isAdmin: true } });
    expect(screen.getByTestId('grace-banner').textContent).toContain(
      '11 days left before read-only mode',
    );
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(screen.queryByTestId('grace-banner')).toBeNull();
    unmount();

    renderUi(<LicenceBanners />, {
      licence: { entitlements: { ...entitlements, admin_warning: false }, isAdmin: false },
    });
    expect(screen.queryByTestId('grace-banner')).toBeNull();
  });

  it('grace banner in Arabic uses the right plural form', () => {
    const entitlements = fakeEntitlements({ state: 'grace', days_left: 2, admin_warning: true });
    renderUi(<LicenceBanners />, { locale: 'ar', licence: { entitlements, isAdmin: true } });
    expect(screen.getByTestId('grace-banner').textContent).toContain('تبقّى يومان');
  });

  it('write buttons are disabled with an explanation in read-only mode', async () => {
    renderUi(<WriteButton>Save</WriteButton>, { licence: { writable: false } });
    expect(screen.getByRole('button', { name: 'Save' }).hasAttribute('disabled')).toBe(true);
    fireEvent.mouseEnter(screen.getByTestId('read-only-action'));
    expect(await screen.findByText(/Not available in read-only mode/)).toBeDefined();
  });
});

describe('error reporting', () => {
  it('shows a refusal translated, never the code, and without a reference (QA WP-029 BUG-02)', async () => {
    renderUi(<span />);
    act(() => {
      reportError(
        new ApiError(403, problem(403, 'technician_limit_reached', { request_id: 'req-41' }), null),
      );
    });
    expect(await screen.findByText(/All technician seats/)).toBeDefined();
    expect(screen.queryByText(/technician_limit_reached/)).toBeNull();
    expect(screen.queryByRole('button', { name: /Copy reference/ })).toBeNull();
  });

  it('shows a real failure as a translated toast with a copy-reference action', async () => {
    renderUi(<span />);
    act(() => {
      reportError(
        new ApiError(500, problem(500, 'internal_error', { request_id: 'req-42' }), null),
      );
    });
    expect(screen.queryByText(/internal_error/)).toBeNull();
    const copy = await screen.findByRole('button', { name: /Copy reference/ });
    expect(copy.getAttribute('data-reference')).toBe('req-42');
    fireEvent.click(copy);
    expect(await screen.findByText('Reference copied')).toBeDefined();
  });

  it('shows the reconnecting banner during an outage and clears it when the API answers', async () => {
    const fake = fakeApi({ 'GET /api/v1/health': { body: { status: 'ok', version: '1' } } });
    renderUi(<ConnectivityBanner />);
    expect(screen.queryByTestId('reconnecting-banner')).toBeNull();
    act(() => {
      reportConnectivity('offline');
    });
    expect(screen.getByTestId('reconnecting-banner').textContent).toContain('Reconnecting');
    await waitFor(
      () => {
        expect(screen.queryByTestId('reconnecting-banner')).toBeNull();
      },
      { timeout: 5000 },
    );
    expect(fake.find('GET', '/api/v1/health').length).toBeGreaterThan(0);
    fake.restore();
  });

  it('catches a crash and shows a friendly page with a reference', () => {
    const quiet = console.error;
    console.error = () => undefined;
    function Broken(): never {
      throw new Error('boom');
    }
    renderUi(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );
    console.error = quiet;
    expect(screen.getByText('Something went wrong on this page')).toBeDefined();
    expect(screen.queryByText(/boom/)).toBeNull();
    expect(screen.getByRole('button', { name: /Copy reference/ })).toBeDefined();
  });
});
