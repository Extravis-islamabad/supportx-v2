import { render, screen } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// CMDB polish: the business view list names each view's base CI (display ID and name, a link).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const VIEW = 'b0000000-0000-7000-8000-000000000001';
const BASE = 'b0000000-0000-7000-8000-000000000002';
const now = new Date().toISOString();

function api() {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/cmdb/business-views': {
        body: {
          items: [
            {
              id: VIEW,
              name: 'Mail service map',
              description: null,
              base_ci_id: BASE,
              base_ci: { id: BASE, display_id: 'CI-7', name: 'Mail service' },
              layout: 'radial',
              owner_id: null,
              updated_at: now,
              version: 1,
            },
          ],
          next_cursor: null,
          has_more: false,
          estimated_total: 1,
        },
      },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('CMDB › business views', () => {
  it('lists each view with its base CI, linked', async () => {
    setDefaultClientFactory(inertClientFactory);
    api();
    window.history.pushState({}, '', '/cmdb/views');
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App />
      </ConfigProvider>,
    );
    // A narrow screen (jsdom) shows cards; the base CI link is the same in both shapes.
    const base = await screen.findByTestId(`cmdb-view-base-${VIEW}`);
    expect(base.textContent).toContain('CI-7');
    expect(base.textContent).toContain('Mail service');
    expect(base.getAttribute('href')).toBe(`/cmdb/${BASE}`);
    expect(screen.getByTestId('cmdb-views-cards').textContent).toContain('Base CI');
  });
});
