import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  fakeConversationEntry,
  fakeFileRules,
  fakeFileStatus,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeStoredFile,
} from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession } from '../../../test/api';

// WP-022 screens: Admin › Files, the administrators' banner, an incident's attachments.
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

describe('Admin › Files', () => {
  afterEach(() => {
    restore();
  });

  it('shows rules, usage and scanning, and saves the rules with If-Match', async () => {
    window.history.pushState({}, '', '/admin/files');
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/files/settings/rules': { body: fakeFileRules({ version: 1 }) },
        'GET /api/v1/files/settings/usage': {
          body: { bytes_used: 12_500_000_000, files: 340, limit_bytes: 50_000_000_000 },
        },
        'PUT /api/v1/files/settings/rules': {
          body: fakeFileRules({ max_file_mb: 40, version: 2 }),
        },
      },
    });
    render(<App />);
    expect(await screen.findByText('12.5 GB of 50 GB used')).toBeTruthy();
    expect(screen.getByText('340 files')).toBeTruthy();
    expect(
      screen.getByText('Every new file is checked for malware before anyone can open it.'),
    ).toBeTruthy();
    const size = screen.getByRole<HTMLInputElement>('spinbutton', { name: 'Largest file (MB)' });
    await waitFor(() => {
      expect(size.value).toBe('25');
    });
    fireEvent.change(size, { target: { value: '40' } });
    fireEvent.click(screen.getByTestId('files-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/files/settings/rules')).toHaveLength(1);
    });
    const [saved] = fake.find('PUT', '/api/v1/files/settings/rules');
    expect(saved?.headers.get('If-Match')).toBe('"1"');
    expect(saved?.body).toMatchObject({ max_file_mb: 40, max_batch: 20 });
    expect(await screen.findByText('File rules saved')).toBeTruthy();
  });

  it('warns administrators everywhere when scanning needs attention, never silently', async () => {
    window.history.pushState({}, '', '/');
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/files/settings/status': {
          body: fakeFileStatus({
            scanner_installed: false,
            scanner_reachable: false,
            warnings: ['scanner_not_installed'],
          }),
        },
      },
    });
    render(<App />);
    const banner = await screen.findByTestId('files-banner');
    expect(banner.textContent).toContain('File scanning needs attention');
    expect(banner.textContent).toContain('No malware scanner is installed: files are not checked.');
  });

  it('technicians do not see the banner or the tab', async () => {
    window.history.pushState({}, '', '/');
    api({
      routes: {
        'GET /api/v1/files/settings/status': {
          body: fakeFileStatus({ warnings: ['signatures_stale'] }),
        },
      },
    });
    render(<App />);
    expect(await screen.findByTestId('user-menu')).toBeTruthy();
    expect(screen.queryByTestId('files-banner')).toBeNull();
  });
});

describe('incident attachments', () => {
  afterEach(() => {
    restore();
  });

  it('lists the record’s files with their state, and a private note’s files as staff only', async () => {
    const item = fakeIncident();
    const path = `/api/v1/incidents/${item.id}`;
    window.history.pushState({}, '', `/incidents/${item.id}`);
    const entryId = '01900000-0000-7000-8000-0000000c0e01';
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
        'GET /api/v1/incidents/categories': { body: [] },
        'GET /api/v1/organization/groups': { body: [] },
        'GET /api/v1/organization/sites': { body: [] },
        'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
        'GET /api/v1/incidents/reply-templates': { body: [] },
        [`GET ${path}`]: { body: item },
        [`GET ${path}/followers`]: { body: { items: [], may_manage: true, people: {} } },
        [`GET ${path}/conversation`]: {
          body: {
            items: [fakeConversationEntry({ id: entryId })],
            truncated: false,
            people: {},
          },
        },
        [`GET /api/v1/files/records/incident/${item.id}`]: {
          body: [
            fakeStoredFile({ owner_id: item.id, record_id: item.id }),
            fakeStoredFile({
              id: '01900000-0000-7000-8000-0000000f0002',
              name: 'payroll.xlsx',
              kind: 'other',
              content_type: 'application/zip',
              previewable: false,
              state: 'scanning',
              openable: false,
              owner_type: 'conversation_entry',
              owner_id: entryId,
              record_id: item.id,
            }),
          ],
        },
      },
    });
    render(<App />);
    // The record's files sit with the description, on Details (the record opens on Conversation).
    fireEvent.click(await screen.findByRole('tab', { name: 'Details' }));
    const record = await screen.findByTestId('inc-attachments');
    expect(await within(record).findByText('invoice.pdf')).toBeTruthy();
    expect(within(record).getByText('Ready')).toBeTruthy();
    expect(within(record).getByRole('button', { name: 'Preview: invoice.pdf' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: /conversation/i }));
    const entryFiles = await screen.findByTestId('conv-entry-files');
    expect(within(entryFiles).getByText('payroll.xlsx')).toBeTruthy();
    expect(within(entryFiles).getByText('Checking for malware')).toBeTruthy();
    expect(within(entryFiles).getByText('Staff only')).toBeTruthy();
    expect(within(entryFiles).queryByRole('button', { name: 'Download: payroll.xlsx' })).toBeNull();
  });
});
