import { render } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { describe, expect, it } from 'vitest';

import { Drawer } from './Drawer';

function panel(direction: 'ltr' | 'rtl', placement?: 'left' | 'right' | 'top' | 'bottom') {
  render(
    <ConfigProvider direction={direction}>
      <Drawer open placement={placement} title="Panel">
        body
      </Drawer>
    </ConfigProvider>,
  );
  const root = document.querySelector('.ant-drawer');
  return ['left', 'right', 'top', 'bottom'].find((side) =>
    root?.classList.contains(`ant-drawer-${side}`),
  );
}

describe('Drawer (coordinator, 2026-11-13)', () => {
  it('opens at the end of the reading direction: right in English, left in Arabic', () => {
    expect(panel('ltr')).toBe('right');
    document.body.innerHTML = '';
    expect(panel('rtl')).toBe('left');
  });

  it('keeps a placement given on purpose', () => {
    expect(panel('rtl', 'right')).toBe('right');
    document.body.innerHTML = '';
    expect(panel('ltr', 'bottom')).toBe('bottom');
  });
});
