import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FormFooter } from './FormPage';

// QA V-01: a field reached by Tab is scrolled clear of the sticky footer bar.

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.documentElement.style.scrollPaddingBottom = '';
});

describe('useClearOfBar', () => {
  it('keeps the bar’s height clear while the footer is shown, and gives it back after', () => {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {
          return undefined;
        }
        disconnect() {
          return undefined;
        }
      },
    );
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(48);
    document.documentElement.style.scrollPaddingBottom = '4px';
    const view = render(<FormFooter primary={<button type="button">Save</button>} testId="f" />);
    expect(document.documentElement.style.scrollPaddingBottom).toBe('64px'); // 48 + SPACE.md
    expect(view.getByTestId('f').hasAttribute('data-sticky-footer')).toBe(true);
    view.unmount();
    expect(document.documentElement.style.scrollPaddingBottom).toBe('4px');
  });
});
