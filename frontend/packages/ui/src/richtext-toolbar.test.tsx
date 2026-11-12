import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { RichTextField } from './richtext';
import { renderUi } from './test/render';

// QA10V-21: the toolbar stays on one row. It measures whether its tools fit (lane C's polish,
// replacing fixed 900/560 px steps): too wide, the alignment and block tools fold into a menu
// each; still too wide, it scrolls sideways. jsdom has no layout, so the toolbar's width is given
// here and its tools' width follows what is shown: the full set needs 1100 px, the compact 600.

type Editable = HTMLElement & { editor: { getHTML: () => string } };

function toolbarWidth(width: number) {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(width);
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    if (this.getAttribute('role') !== 'toolbar') return 0;
    return this.querySelector('[data-testid="rt-align-center"]') === null ? 600 : 1100;
  });
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

  it('a toolbar too narrow even when compact scrolls sideways in one row', async () => {
    toolbarWidth(390);
    renderUi(<RichTextField label="Note" testId="ed" />);
    await screen.findByTestId('ed');
    const bar = await screen.findByRole('toolbar');
    await waitFor(() => {
      expect(bar.style.overflowX).toBe('auto');
    });
    expect(screen.queryByTestId('rt-align-menu')).not.toBeNull(); // compact too
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

describe('the requester toolbar (QA 2026-11-12 F-09)', () => {
  it('basic keeps text, lists, links and a quote, and offers no code, table or line', async () => {
    renderUi(<RichTextField label="Details" basic testId="basic" />);
    expect(await screen.findByTestId('rt-bold')).toBeDefined();
    expect(screen.getByTestId('rt-quote')).toBeDefined();
    for (const tool of ['rt-code', 'rt-code-block', 'rt-table', 'rt-hr']) {
      expect(screen.queryByTestId(tool)).toBeNull();
    }
  });
});
