import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { RichTextField } from './richtext';
import { renderUi } from './test/render';

// QA10V-21: the toolbar stays on one row: below about 900 px the alignment and block tools fold
// into a menu each. jsdom has no layout, so the toolbar's width is given here.

type Editable = HTMLElement & { editor: { getHTML: () => string } };

function toolbarWidth(width: number) {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(width);
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(private readonly callback: () => void) {}
      observe() {
        this.callback();
      }
      disconnect() {
        // nothing to stop: the stub reports once, on observe
      }
    },
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('rich-text toolbar (QA10V-21)', () => {
  it('a compact toolbar folds alignment and block tools into menus that still work', async () => {
    toolbarWidth(700);
    renderUi(<RichTextField label="Note" testId="ed" />);
    const area = await screen.findByTestId<Editable>('ed');
    await waitFor(() => {
      expect(screen.queryByTestId('rt-align-menu')).not.toBeNull();
    });
    expect(screen.queryByTestId('rt-align-center')).toBeNull();
    expect(screen.queryByTestId('rt-table')).toBeNull();
    expect(screen.getByTestId('rt-more-menu').getAttribute('aria-label')).toBe('More formatting');
    // Bold and the lists stay as buttons.
    expect(screen.getByTestId('rt-bold')).not.toBeNull();
    expect(screen.getByTestId('rt-bullets')).not.toBeNull();
    fireEvent.click(screen.getByTestId('rt-more-menu'));
    fireEvent.click(await screen.findByTestId('rt-hr'));
    await waitFor(() => {
      expect(area.editor.getHTML()).toContain('<hr');
    });
  });

  it('a wide toolbar keeps every tool as a button', async () => {
    toolbarWidth(1200);
    renderUi(<RichTextField label="Note" testId="ed" />);
    await screen.findByTestId('ed');
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByTestId('rt-align-center')).not.toBeNull();
    expect(screen.getByTestId('rt-table')).not.toBeNull();
    expect(screen.queryByTestId('rt-align-menu')).toBeNull();
  });
});
