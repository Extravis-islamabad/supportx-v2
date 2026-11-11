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
  it('shows only the way there is more to see, outside the tab list, and scrolls on a click', () => {
    overflowing(0);
    const scrollBy = vi.fn();
    HTMLElement.prototype.scrollBy = scrollBy;
    render(
      <AppearanceProvider initialMode="light">
        <Tabs items={items} />
      </AppearanceProvider>,
    );
    const later = screen.getByTestId('tabs-scroll-later');
    expect(screen.queryByTestId('tabs-scroll-earlier')).toBeNull();
    expect(later.closest('[role="tablist"]')).toBeNull();
    expect(later.getAttribute('aria-label')).toBe('Later tabs');
    fireEvent.click(later);
    expect(scrollBy).toHaveBeenCalledWith({ left: 210, behavior: 'smooth' });
  });

  it('at the end of the row only the way back is offered', () => {
    overflowing(600);
    render(
      <AppearanceProvider initialMode="light">
        <Tabs items={items} />
      </AppearanceProvider>,
    );
    act(() => {
      document.querySelector('.ant-tabs-nav-wrap')?.dispatchEvent(new Event('scroll'));
    });
    expect(screen.getByTestId('tabs-scroll-earlier')).toBeTruthy();
    expect(screen.queryByTestId('tabs-scroll-later')).toBeNull();
  });

  it('a row that fits has no buttons', () => {
    render(<Tabs items={items.slice(0, 2)} />);
    expect(screen.queryByTestId('tabs-scroll-later')).toBeNull();
    expect(screen.queryByTestId('tabs-scroll-earlier')).toBeNull();
  });
});
