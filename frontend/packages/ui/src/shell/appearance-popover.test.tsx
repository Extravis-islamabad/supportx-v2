import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import type { NavLayout } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';

import { renderUi } from '../test/render';
import { AppHeader } from './AppHeader';
import { AppShell } from './AppShell';

/**
 * The Appearance popover must close on the first click after a layout or language change
 * (WP-014 follow-up, fixed in WP-020). A layout change renders a different shell tree, which
 * used to remount the header and lose the popover's own open state.
 */
function Harness() {
  const [layout, setLayout] = useState<NavLayout>('top');
  const session = fakeSession({ nav_layout: layout });
  return (
    <AppShell
      layout={layout}
      nav={[]}
      activeKey="home"
      onNavigate={() => undefined}
      header={(topNav) => (
        <AppHeader
          appName="app.console.name"
          session={session}
          start={topNav ?? undefined}
          onLogout={() => undefined}
          onNavLayoutChange={setLayout}
        />
      )}
    >
      <div>content</div>
    </AppShell>
  );
}

/**
 * Whether the popover is open, as its trigger reports it (the controlled state). jsdom runs no
 * CSS animations, so the panel's own hiding cannot be observed here; e2e covers the browser
 * (layouts.spec.ts, with no retry).
 */
function isOpen(): boolean {
  return screen.getByTestId('appearance-menu').getAttribute('aria-expanded') === 'true';
}

async function openPopover() {
  fireEvent.click(screen.getByTestId('appearance-menu'));
  await waitFor(() => {
    expect(isOpen()).toBe(true);
  });
}

describe('Appearance popover', () => {
  it('baseline: opens and closes with one click each', async () => {
    renderUi(<Harness />);
    await openPopover();
    fireEvent.click(screen.getByTestId('appearance-menu'));
    await waitFor(() => {
      expect(isOpen()).toBe(false);
    });
  });

  it('closes on the first click after a layout change', async () => {
    renderUi(<Harness />);
    await openPopover();
    await act(async () => {
      fireEvent.click(screen.getByText('Side bar'));
      await Promise.resolve();
    });
    // Still open after the change (the user may want to change more).
    expect(isOpen()).toBe(true);
    fireEvent.click(screen.getByTestId('appearance-menu'));
    await waitFor(() => {
      expect(isOpen()).toBe(false);
    });
  });

  it('closes on the first click after a language change', async () => {
    renderUi(<Harness />);
    await openPopover();
    fireEvent.mouseDown(
      screen.getByTestId('language-select').querySelector('.ant-select-selector') ??
        screen.getByTestId('language-select'),
    );
    const option = await screen.findByTitle('العربية');
    await act(async () => {
      fireEvent.click(option);
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(document.documentElement.getAttribute('dir')).toBe('rtl');
    });
    fireEvent.click(screen.getByTestId('appearance-menu'));
    await waitFor(() => {
      expect(isOpen()).toBe(false);
    });
  });
});
