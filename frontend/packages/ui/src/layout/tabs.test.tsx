import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AppearanceProvider } from '../AppearanceProvider';

import { Tabs } from './Tabs';

// QA 2026-11-11 F-06/V-04: a tab row that does not fit scrolls by buttons that sit outside the
// tab list (axe aria-required-children), so every tab is reachable by mouse.

const items = Array.from({ length: 9 }, (_, i) => ({
  key: `t${String(i)}`,
  label: `Tab ${String(i)}`,
  children: `Body ${String(i)}`,
}));

afterEach(() => {
  vi.restoreAllMocks();
});

function overflowing(scrollLeft: number) {
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(900);
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300);
  vi.spyOn(HTMLElement.prototype, 'scrollLeft', 'get').mockReturnValue(scrollLeft);
}

describe('Tabs', () => {
  it('shows its buttons beside the row, outside the tab list, and scrolls on a click', () => {
    overflowing(0);
    const scrollBy = vi.fn();
    HTMLElement.prototype.scrollBy = scrollBy;
    render(
      <AppearanceProvider initialMode="light">
        <Tabs items={items} />
      </AppearanceProvider>,
    );
    const later = screen.getByTestId('tabs-scroll-later');
    // Both show while the row overflows; the way with nothing more is disabled.
    expect(screen.getByTestId('tabs-scroll-earlier').hasAttribute('disabled')).toBe(true);
    expect(later.hasAttribute('disabled')).toBe(false);
    expect(later.closest('[role="tablist"]')).toBeNull();
    // The scrolling part is narrowed so the buttons sit beside it, never over a tab.
    const wrap = document.querySelector<HTMLElement>('.ant-tabs-nav-wrap');
    expect(wrap?.style.marginInline).toBe('32px');
    expect(later.getAttribute('aria-label')).toBe('Later tabs');
    fireEvent.click(later);
    expect(scrollBy).toHaveBeenCalledWith({ left: 210, behavior: 'smooth' });
  });

  it('at the end of the row only the way back can be used', () => {
    overflowing(600);
    render(
      <AppearanceProvider initialMode="light">
        <Tabs items={items} />
      </AppearanceProvider>,
    );
    act(() => {
      document.querySelector('.ant-tabs-nav-wrap')?.dispatchEvent(new Event('scroll'));
    });
    expect(screen.getByTestId('tabs-scroll-earlier').hasAttribute('disabled')).toBe(false);
    expect(screen.getByTestId('tabs-scroll-later').hasAttribute('disabled')).toBe(true);
  });

  it('a row that fits has no buttons', () => {
    render(<Tabs items={items.slice(0, 2)} />);
    expect(screen.queryByTestId('tabs-scroll-later')).toBeNull();
    expect(screen.queryByTestId('tabs-scroll-earlier')).toBeNull();
  });
  it('a pressed tab is chosen by its click without taking focus first', () => {
    overflowing(300);
    let selected = 't0';
    const view = render(
      <AppearanceProvider initialMode="light">
        <Tabs
          items={items}
          onChange={(key) => {
            selected = key;
          }}
        />
      </AppearanceProvider>,
    );
    const tab = view.getByRole('tab', { name: 'Tab 7' });
    // The press is cancelled (so focus, and Ant Design's scroll reset, never happen) ...
    expect(fireEvent.mouseDown(tab, { button: 0 })).toBe(false);
    // ... and the click still chooses the tab.
    fireEvent.click(tab);
    expect(selected).toBe('t7');
  });
});
