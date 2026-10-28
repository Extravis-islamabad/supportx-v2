import { render, screen } from '@testing-library/react';
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

  it('BUG-06: the top menu keeps its overflow inside its own box, never under the next button', () => {
    render(
      <AppearanceProvider>
        <AppShell
          nav={[{ key: 'home', path: '/', labelKey: 'nav.home', locked: false }]}
          activeKey="home"
          layout="top"
          onNavigate={() => undefined}
          header={(start) => start}
        >
          <span />
        </AppShell>
      </AppearanceProvider>,
    );
    expect(screen.getByTestId('nav-top').style.overflow).toBe('hidden');
  });
});
