import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';

import { AppearanceProvider } from '../AppearanceProvider';
import { AppHeader } from './AppHeader';
import { AppShell } from './AppShell';

// WP-036 QA round, header findings at 390 px (~/Desktop/qa-wp036/QA-REPORT.md BUG-06, BUG-07).

/** A 390 px wide screen for Ant Design's breakpoints (jsdom has no media queries). */
function phoneWidth(): void {
  vi.stubGlobal('matchMedia', (query: string) => {
    const min = /min-width:\s*([\d.]+)px/.exec(query);
    const max = /max-width:\s*([\d.]+)px/.exec(query);
    const matches =
      (min === null || 390 >= Number(min[1])) && (max === null || 390 <= Number(max[1]));
    return {
      matches,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    };
  });
}

describe('WP-036 QA: the header at 390 px', () => {
  beforeEach(phoneWidth);
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('BUG-07: the user menu is named by its own content, so its name and what it shows agree', () => {
    const session = fakeSession();
    render(
      <AppearanceProvider>
        <AppHeader appName="app.console.name" session={session} onLogout={() => undefined} />
      </AppearanceProvider>,
    );
    const menu = screen.getByTestId('user-menu');
    // No aria-label that differs from the visible initials (axe label-content-name-mismatch).
    expect(menu.getAttribute('aria-label')).toBeNull();
    expect(
      screen.getByRole('button', { name: `Menu: ${session.user.display_name}` }),
    ).toBeDefined();
  });

  // BUG-06's band (overflow inside its own box) is for wider screens now: below the phone
  // breakpoint every layout gives way to a drawer behind a menu button (QA 2026-11-05 V2).
  it.each(['side', 'side_compact', 'top'] as const)(
    'V2: at 390 px the %s layout leaves no rail or band, only a menu button and a drawer',
    async (layout) => {
      render(
        <AppearanceProvider>
          <AppShell
            nav={[{ key: 'home', path: '/', labelKey: 'nav.home', locked: false }]}
            activeKey="home"
            layout={layout}
            onNavigate={() => undefined}
            header={(_top, menu) => <header>{menu}</header>}
          >
            <span />
          </AppShell>
        </AppearanceProvider>,
      );
      expect(screen.queryByTestId('nav-side')).toBeNull();
      expect(screen.queryByTestId('nav-compact')).toBeNull();
      expect(screen.queryByTestId('nav-top')).toBeNull();
      const button = screen.getByRole('button', { name: 'Open the menu' });
      expect(button.getAttribute('aria-expanded')).toBe('false');
      // The navigation is in the page while closed (forceRender), with every section's key.
      expect(document.querySelector('nav[data-items]')?.getAttribute('data-items')).toBe('home');
      fireEvent.click(button);
      await waitFor(() => {
        expect(button.getAttribute('aria-expanded')).toBe('true');
      });
    },
  );
});
