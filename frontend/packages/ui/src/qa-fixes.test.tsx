import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';

import { AppearanceProvider } from './AppearanceProvider';
import { PresenceAvatars } from './PresenceAvatars';
import { AppHeader } from './shell/AppHeader';

// WP-020-FIX: shared UI findings of the WP-020 QA report, named after their IDs.

describe('QA findings in the shared UI', () => {
  it('BUG-13: your other window shows your initials, never "Y(" from the label', () => {
    render(
      <AppearanceProvider>
        <PresenceAvatars
          selfUserId="u-1"
          viewers={[{ clientId: 'c-2', userId: 'u-1', name: 'Amal Admin' }]}
        />
      </AppearanceProvider>,
    );
    const presence = screen.getByTestId('presence');
    expect(presence.getAttribute('aria-label')).toContain('You (another window)');
    expect(within(presence).getByText('AA')).toBeDefined();
    expect(presence.textContent).not.toContain('Y(');
  });

  it('BUG-15: Escape closes the Appearance panel while the focus is inside it', async () => {
    render(
      <AppearanceProvider>
        <AppHeader appName="app.console.name" session={fakeSession()} onLogout={() => undefined} />
      </AppearanceProvider>,
    );
    const trigger = screen.getByTestId('appearance-menu');
    fireEvent.click(trigger);
    await waitFor(() => {
      expect(trigger.getAttribute('aria-expanded')).toBe('true');
    });
    const select = await screen.findByTestId('language-select');
    fireEvent.keyDown(select, { key: 'Escape' });
    await waitFor(() => {
      expect(trigger.getAttribute('aria-expanded')).toBe('false');
    });
  });

  it('BUG-04: picking a language hands it to the app to store with the user', async () => {
    const stored = vi.fn();
    render(
      <AppearanceProvider>
        <AppHeader
          appName="app.console.name"
          session={fakeSession()}
          onLogout={() => undefined}
          onLocaleChange={stored}
        />
      </AppearanceProvider>,
    );
    fireEvent.click(screen.getByTestId('appearance-menu'));
    const select = await screen.findByTestId('language-select');
    const selector = select.querySelector('.ant-select-selector');
    if (selector === null) throw new Error('no selector');
    fireEvent.mouseDown(selector);
    fireEvent.click(await screen.findByTitle('العربية'));
    expect(stored).toHaveBeenCalledWith('ar');
    await waitFor(() => {
      expect(document.documentElement.dir).toBe('rtl');
    });
  });
});
