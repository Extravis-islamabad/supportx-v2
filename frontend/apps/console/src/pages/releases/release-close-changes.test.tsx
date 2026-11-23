import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue } from '@supportx/api-client/testing';
import { AppearanceProvider, createQueryClient } from '@supportx/ui';

import { consoleApi } from '../../test/api';
import { ReleaseChangesClose } from './ReleaseChangesClose';

// REQ-REL-052 (WP-058b S5a): in a closing release's move dialog, close its changes you may close;
// each result says closed, or why not.

const REL_ID = '01a1a2b3-0000-7000-8000-0000000e0001';
const CHG_A = '01a1a2b3-0000-7000-8000-0000000e0a01';
const CHG_B = '01a1a2b3-0000-7000-8000-0000000e0a02';

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function Offer() {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      <AppearanceProvider>
        <ReleaseChangesClose releaseId={REL_ID} />
      </AppearanceProvider>
    </QueryClientProvider>
  );
}

const change = (id: string, display: string, category: string) => ({
  id,
  visible: true,
  display_id: display,
  subject: `${display} work`,
  stage: 'review',
  status: 'review_in_progress',
  status_category: category,
});

describe('closing a release closes its changes you may close', () => {
  it('REQ-REL-052: one closes, one is skipped with the reason in words', async () => {
    const settings = fakeIncidentCatalogue();
    settings.closure_codes = [
      {
        code: 'successful',
        labels: { en: 'Successful' },
        disabled: false,
        colour: null,
        sort_order: 1,
      },
    ];
    const fake = consoleApi({
      routes: {
        [`GET /api/v1/releases/${REL_ID}/changes`]: {
          body: [change(CHG_A, 'CHG-1', 'resolved'), change(CHG_B, 'CHG-2', 'open')],
        },
        'GET /api/v1/changes/settings': { body: settings },
        [`POST /api/v1/releases/${REL_ID}/changes/close`]: {
          body: [
            { id: CHG_A, display_id: 'CHG-1', closed: true },
            {
              id: CHG_B,
              display_id: 'CHG-2',
              closed: false,
              code: 'not_closable_from_here',
              params: {},
              field: null,
            },
          ],
        },
      },
    });
    restore = fake.restore;
    render(<Offer />);
    const offer = await screen.findByTestId('release-close-changes');
    const select = within(offer)
      .getByTestId('release-close-changes-code')
      .querySelector('.ant-select-selector');
    if (select === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(select);
    fireEvent.click(await screen.findByTitle('Successful'));
    fireEvent.click(screen.getByTestId('release-close-changes-run'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/releases/${REL_ID}/changes/close`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/releases/${REL_ID}/changes/close`);
    expect(sent?.body).toEqual({ closure_code: 'successful' });
    const results = await screen.findByTestId('release-close-changes-results');
    expect(results.textContent).toContain('CHG-1');
    expect(results.textContent).toContain('Closed');
    expect(results.textContent).toContain('It cannot be closed from where it is now');
  });

  it('shows nothing when every change is closed already', async () => {
    const fake = consoleApi({
      routes: {
        [`GET /api/v1/releases/${REL_ID}/changes`]: {
          body: [change(CHG_A, 'CHG-1', 'closed')],
        },
        'GET /api/v1/changes/settings': { body: fakeIncidentCatalogue() },
      },
    });
    restore = fake.restore;
    render(<Offer />);
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/releases/${REL_ID}/changes`)).toHaveLength(1);
    });
    expect(screen.queryByTestId('release-close-changes')).toBeNull();
  });
});
