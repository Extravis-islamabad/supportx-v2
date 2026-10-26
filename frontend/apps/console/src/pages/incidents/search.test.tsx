import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';
import { AppearanceProvider, createQueryClient } from '@supportx/ui';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';
import { IncidentPicker } from './IncidentPicker';
import { recentIncidents, rememberIncident } from './recent';

// WP-027 (REQ-INC-085): quick search in the command palette and the incident picker.
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const TECH = fakeSession({ display_name: 'Tariq Tech', roles: ['technician'] });
const AHMED = '01900000-0000-7000-8000-0000000002a1';
const PEOPLE = { [AHMED]: { display_name: 'Ahmed Khan', email: 'ahmed.khan@demo.test' } };
const PRINTER = fakeIncident({
  id: '01900000-0000-7000-8000-00000000c007',
  display_id: 'INC-7',
  subject: 'Printer on floor 3 is down',
  status: 'in_progress',
  status_category: 'open',
});
const TONER = fakeIncident({
  id: '01900000-0000-7000-8000-00000000c008',
  display_id: 'INC-8',
  subject: 'Printer toner is low',
  status: 'resolved',
  status_category: 'resolved',
});

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  restore();
});

describe('command palette search', () => {
  it('finds incidents by what is typed and opens the chosen one', async () => {
    const fake = api({
      me: TECH,
      routes: {
        'GET /api/v1/incidents/search': { body: { items: [PRINTER, TONER], people: PEOPLE } },
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
        [`GET /api/v1/incidents/${PRINTER.id}`]: { body: PRINTER },
      },
    });
    render(<App />);
    await screen.findByTestId('user-name');
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = await screen.findByRole('combobox', { name: 'Type a page name…' });
    fireEvent.change(input, { target: { value: 'printr' } });
    const option = await screen.findByTestId('palette-incident-INC-7');
    // People and statuses in words, never codes or IDs.
    expect(option.textContent).toContain('INC-7 · Printer on floor 3 is down');
    expect(option.textContent).toContain('Ahmed Khan · In progress');
    expect(within(screen.getByRole('dialog')).getByText('Incidents')).toBeTruthy();
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/incidents/search').at(-1);
      expect(last?.url.searchParams.get('q')).toBe('printr');
    });
    fireEvent.click(option);
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/incidents/${PRINTER.id}`);
    });
  });

  it('offers recently viewed incidents before anything is typed, in viewing order', async () => {
    rememberIncident(TECH.user.id, TONER.id);
    rememberIncident(TECH.user.id, PRINTER.id);
    expect(recentIncidents(TECH.user.id)).toEqual([PRINTER.id, TONER.id]);
    const fake = api({
      me: TECH,
      routes: {
        // The server answers in its own order; the palette shows the viewing order.
        'GET /api/v1/incidents/search': { body: { items: [TONER, PRINTER], people: PEOPLE } },
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      },
    });
    render(<App />);
    await screen.findByTestId('user-name');
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(await screen.findByText('Recently viewed')).toBeTruthy();
    const first = await screen.findByTestId('palette-incident-INC-7');
    const second = screen.getByTestId('palette-incident-INC-8');
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const call = fake.find('GET', '/api/v1/incidents/search').at(-1);
    expect(call?.url.searchParams.getAll('ids')).toEqual([PRINTER.id, TONER.id]);
    expect(call?.url.searchParams.get('q')).toBeNull();
  });
});

function Picker({ from }: { from?: { id: string; requesterId: string; requesterName: string } }) {
  const [client] = useState(createQueryClient);
  const [value, setValue] = useState<string | null>(null);
  return (
    <QueryClientProvider client={client}>
      <AppearanceProvider>
        <IncidentPicker
          value={value}
          onChange={(id) => {
            setValue(id);
          }}
          from={from}
          testId="pick"
          ariaLabel="Incident to link"
        />
        <output data-testid="picked">{value}</output>
      </AppearanceProvider>
    </QueryClientProvider>
  );
}

describe('incident picker (links and merges)', () => {
  it('offers the same requester’s incidents, never the record itself, then searches', async () => {
    rememberIncident(TECH.user.id, PRINTER.id);
    const fake = api({
      me: TECH,
      routes: {
        'GET /api/v1/incidents/search': { body: { items: [PRINTER, TONER], people: PEOPLE } },
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      },
    });
    render(<Picker from={{ id: PRINTER.id, requesterId: AHMED, requesterName: 'Ahmed Khan' }} />);
    const select = screen.getByRole('combobox', { name: 'Incident to link' });
    fireEvent.mouseDown(select);
    expect(await screen.findByText('Also from Ahmed Khan')).toBeTruthy();
    expect(await screen.findByTestId('pick-option-INC-8')).toBeTruthy();
    expect(screen.queryByTestId('pick-option-INC-7')).toBeNull(); // the record being linked
    await waitFor(() => {
      const calls = fake.find('GET', '/api/v1/incidents/search');
      expect(calls.some((c) => c.url.searchParams.get('requester_id') === AHMED)).toBe(true);
    });
    // Typing searches everything the user may see, narrowed by status if asked.
    fireEvent.change(select, { target: { value: 'INC-8' } });
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/incidents/search').at(-1);
      expect(last?.url.searchParams.get('q')).toBe('INC-8');
    });
    expect(await screen.findByText('Matching incidents')).toBeTruthy();
    const option = await screen.findByTestId('pick-option-INC-8');
    expect(within(option).getByText('Resolved', { exact: false })).toBeTruthy();
    fireEvent.click(option);
    await waitFor(() => {
      expect(screen.getByTestId('picked').textContent).toBe(TONER.id);
    });
  });

  it('narrows by status', async () => {
    const fake = api({
      me: TECH,
      routes: {
        'GET /api/v1/incidents/search': { body: { items: [], people: {} } },
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      },
    });
    render(<Picker />);
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Status' }));
    fireEvent.click(await screen.findByTitle('Waiting'));
    const select = screen.getByRole('combobox', { name: 'Incident to link' });
    fireEvent.mouseDown(select);
    fireEvent.change(select, { target: { value: 'mail' } });
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/incidents/search').at(-1);
      expect(last?.url.searchParams.getAll('status_category')).toEqual(['paused']);
    });
    expect(await screen.findByText('No incident you can see matches')).toBeTruthy();
  });
});
