import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { AppearanceProvider, createQueryClient } from '@supportx/ui';

import { consoleApi } from '../../test/api';
import { KnownErrorTool } from './KnownErrorTool';

// WP-044b s3 (REQ-PRB-038): known errors suggested in an incident's editor; applying one links
// the incident to the problem and puts the workaround at the caret, without sending anything.

const INC = '01a1a2b3-0000-7000-8000-00000000c101';
const PRB = '01a1a2b3-0000-7000-8000-00000000e001';

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function Tool() {
  const [client] = useState(createQueryClient);
  const [text, setText] = useState('');
  return (
    <QueryClientProvider client={client}>
      <AppearanceProvider>
        <KnownErrorTool incidentId={INC} insert={setText} />
        <output data-testid="inserted">{text}</output>
      </AppearanceProvider>
    </QueryClientProvider>
  );
}

describe('known errors in the incident editor', () => {
  it('suggests, then links and inserts the workaround (nothing sent)', async () => {
    const fake = consoleApi({
      routes: {
        'GET /api/v1/problems/known-errors/suggestions': {
          body: [
            {
              id: PRB,
              display_id: 'PRB-7',
              subject: 'Mail relay drops messages',
              status: 'investigating',
              symptoms: null,
              workaround: '<p>Restart the relay.</p>',
              known_error_at: '2026-11-01T08:00:00Z',
              retired_at: null,
              incidents: 2,
            },
          ],
        },
        [`POST /api/v1/problems/${PRB}/incidents`]: { body: { linked: true } },
      },
    });
    restore = fake.restore;
    render(<Tool />);
    fireEvent.click(await screen.findByTestId('inc-known-error-tool'));
    fireEvent.click(
      await screen.findByText('PRB-7 Mail relay drops messages: apply its workaround'),
    );
    await waitFor(() => {
      expect(screen.getByTestId('inserted').textContent).toBe('<p>Restart the relay.</p>');
    });
    const link = fake.calls.find((c) => c.method === 'POST');
    expect(link?.body).toEqual({ incident_id: INC, move: false });
    expect(fake.calls.some((c) => c.path.includes('/conversation'))).toBe(false); // not sent
  });

  it('shows nothing when no known error matches', async () => {
    const fake = consoleApi({
      routes: { 'GET /api/v1/problems/known-errors/suggestions': { body: [] } },
    });
    restore = fake.restore;
    render(<Tool />);
    await waitFor(() => {
      expect(fake.calls.some((c) => c.path.endsWith('/suggestions'))).toBe(true);
    });
    expect(screen.queryByTestId('inc-known-error-tool')).toBeNull();
  });
});
