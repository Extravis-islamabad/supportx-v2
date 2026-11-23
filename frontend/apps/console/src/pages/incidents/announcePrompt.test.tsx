import { QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp } from 'antd';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';

import { AppearanceProvider, createQueryClient } from '@supportx/ui';

import { consoleApi, fakeSession } from '../../test/api';
import { EndAnnouncementsPrompt } from './IncidentAnnouncements';

// WP-046b S4 (REQ-INC-129 AC2; lane C): resolving offers to end the announcements made from the
// incident. The prompt opens once loaded with live ones, "Keep them" closes it, and it closes
// itself when the last live one is ended, so it never comes back on its own later.

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ID = '01900000-0000-7000-8000-00000000c007';
const PATH = `/api/v1/incidents/${ID}`;

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function Prompt({ onClosed }: { onClosed: () => void }) {
  const [client] = useState(createQueryClient);
  const [open, setOpen] = useState(true);
  return (
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AppearanceProvider>
          <AntApp>
            <EndAnnouncementsPrompt
              item={{ id: ID, display_id: 'INC-7' }}
              open={open}
              onClose={() => {
                setOpen(false);
                onClosed();
              }}
            />
          </AntApp>
        </AppearanceProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

describe('Ending announcements on resolve', () => {
  it('"Keep them" closes the prompt and ends nothing', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: {
        [`GET ${PATH}/announcements`]: {
          body: [{ id: 'a-1', display_id: 'ANN-4', title: 'Mail is down', status: 'published' }],
        },
      },
    });
    restore = fake.restore;
    let closed = 0;
    render(<Prompt onClosed={() => (closed += 1)} />);
    fireEvent.click(await screen.findByTestId('inc-announce-prompt-close'));
    await waitFor(() => {
      expect(closed).toBe(1);
    });
    expect(fake.find('POST', `${PATH}/announcements/a-1/end`)).toHaveLength(0);
  });

  it('ending the last live one closes the prompt by itself', async () => {
    let ended = false;
    const fake = consoleApi({
      me: ADMIN,
      routes: {
        [`GET ${PATH}/announcements`]: () => ({
          body: [
            {
              id: 'a-1',
              display_id: 'ANN-4',
              title: 'Mail is down',
              status: ended ? 'archived' : 'published',
            },
          ],
        }),
        [`POST ${PATH}/announcements/a-1/end`]: () => {
          ended = true;
          return {
            body: { id: 'a-1', display_id: 'ANN-4', title: 'Mail is down', status: 'archived' },
          };
        },
      },
    });
    restore = fake.restore;
    let closed = 0;
    render(<Prompt onClosed={() => (closed += 1)} />);
    fireEvent.click(await screen.findByTestId('inc-announcement-end-ANN-4'));
    fireEvent.click(await screen.findByTestId('inc-announcement-end-ok-ANN-4'));
    await waitFor(() => {
      expect(closed).toBe(1);
    });
  });

  it('with nothing live it never opens', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: {
        [`GET ${PATH}/announcements`]: {
          body: [{ id: 'a-2', display_id: 'ANN-2', title: 'Old', status: 'archived' }],
        },
      },
    });
    restore = fake.restore;
    let closed = 0;
    render(<Prompt onClosed={() => (closed += 1)} />);
    await waitFor(() => {
      expect(closed).toBe(1);
    });
    expect(screen.queryByTestId('inc-announce-prompt-close')).toBeNull();
  });
});
