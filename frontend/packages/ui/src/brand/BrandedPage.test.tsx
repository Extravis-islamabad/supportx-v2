import { render, screen } from '@testing-library/react';
import { theme } from 'antd';
import { describe, expect, it } from 'vitest';

import { AppearanceProvider } from '../AppearanceProvider';
import { BrandedPage } from './BrandedPage';

// QA10-P2-02: outside the app frame the page paints its own background, so a dark theme never
// puts a dark card on the browser's white page (where the white-text logo vanished).
describe('BrandedPage', () => {
  it('fills the window with the theme’s page colour, dark in dark mode', () => {
    let expected = '';
    function Probe() {
      expected = theme.useToken().token.colorBgLayout;
      return <p>inside</p>;
    }
    render(
      <AppearanceProvider initialMode="dark">
        <BrandedPage>
          <Probe />
        </BrandedPage>
      </AppearanceProvider>,
    );
    const page = screen.getByText('inside').closest<HTMLElement>('div[style*="position: fixed"]');
    expect(page).not.toBeNull();
    const probe = document.createElement('div');
    probe.style.background = expected;
    expect(page?.style.background).toBe(probe.style.background); // the same colour, normalised
    expect(expected.toLowerCase()).not.toBe('#ffffff');
  });
});
