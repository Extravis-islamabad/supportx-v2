import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { FileRules, StoredFile } from '@supportx/api-client';
import { fakeApi } from '@supportx/api-client/testing';
import { label } from '@supportx/labels';

import { Attachments, extensionOf, FileStateTag, formatSize, refusal } from './files';
import { RichTextView } from './richtext';
import { inlineImageIds } from './richtext/inlineImage';
import { renderUi } from './test/render';

const t = (key: string, params?: Record<string, unknown>) => label(key, 'en', params as never);

const RULES: FileRules = {
  max_file_mb: 1,
  max_batch: 2,
  blocked_extensions: ['exe', 'js'],
  version: 1,
};

function stored(overrides: Partial<StoredFile> = {}): StoredFile {
  return {
    id: '01a17826-97b9-747c-b630-0d20263b86e9',
    name: 'report.pdf',
    size: 2_400_000,
    content_type: 'application/pdf',
    kind: 'pdf',
    state: 'clean',
    openable: true,
    previewable: true,
    has_thumbnail: false,
    owner_type: 'work_item',
    owner_id: '01a17826-9745-76b0-91c1-3930c5929a68',
    record_type: 'incident',
    record_id: '01a17826-9745-76b0-91c1-3930c5929a68',
    inline: false,
    uploaded_by: null,
    created_at: '2026-10-26T10:00:00Z',
    version: 1,
    ...overrides,
  };
}

describe('file rules in the browser (REQ-INC-079 AC2)', () => {
  it('refuses too-large and blocked files before sending, with the limit in words', () => {
    const big = new File([new Uint8Array(1_000_001)], 'video.mp4');
    expect(refusal(big, RULES, t)).toBe('video.mp4 is larger than the limit of 1 MB.');
    const script = new File(['x'], 'run.JS');
    expect(refusal(script, RULES, t)).toBe('run.JS: files of this type (.js) are not allowed.');
    expect(refusal(new File(['x'], 'notes.txt'), RULES, t)).toBeNull();
    expect(refusal(big, undefined, t)).toBeNull(); // the server still checks
  });

  it('reads extensions and sizes like the API', () => {
    expect(extensionOf('archive.tar.GZ')).toBe('gz');
    expect(extensionOf('.bashrc')).toBe('');
    expect(extensionOf('README')).toBe('');
    expect(formatSize(2_400_000, 'en')).toBe('2.4 MB');
    expect(formatSize(512, 'en')).toBe('512 byte');
    expect(formatSize(2_400_000, 'ar')).not.toContain('MB'); // the unit in Arabic
  });
});

describe('Attachments', () => {
  it('shows each file with its state in words; only ready files open', () => {
    const fake = fakeApi({ 'GET /api/v1/files/settings/rules': { body: RULES } });
    renderUi(
      <Attachments
        files={[
          stored(),
          stored({
            id: '01a17826-97b9-747c-b630-0d20263b86ea',
            name: 'eicar.txt',
            state: 'infected',
            openable: false,
            previewable: false,
            kind: 'other',
          }),
        ]}
        canRemove
      />,
    );
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Blocked: malware found')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Preview: report.pdf' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download: report.pdf' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Download: eicar.txt' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Delete: eicar.txt' })).toBeTruthy();
    // No target: nothing can be added here.
    expect(document.querySelector('input[type="file"]')).toBeNull();
    fake.restore();
  });

  it('refuses a too-large file on the spot and lists why', async () => {
    const fake = fakeApi({ 'GET /api/v1/files/settings/rules': { body: RULES } });
    renderUi(
      <Attachments
        files={[]}
        target={{ ownerType: 'work_item', ownerId: '01a17826-9745-76b0-91c1-3930c5929a68' }}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByText(
          'Up to 1 MB each. Files are checked for malware before anyone can open them.',
        ),
      ).toBeTruthy();
    });
    const input = document.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input as HTMLInputElement, {
      target: { files: [new File([new Uint8Array(1_000_001)], 'huge.iso')] },
    });
    // Other alerts (a notification from an earlier test's request) may be on the page too.
    await waitFor(() => {
      expect(screen.getAllByRole('alert').map((a) => a.textContent)).toContain(
        'huge.iso is larger than the limit of 1 MB.',
      );
    });
    expect(fake.calls.some((c) => c.method === 'POST')).toBe(false);
    fake.restore();
  });

  it('marks a private note’s files as staff only', () => {
    const fake = fakeApi({ 'GET /api/v1/files/settings/rules': { body: RULES } });
    renderUi(<Attachments files={[stored()]} staffOnly />);
    expect(screen.getByText('Staff only')).toBeTruthy();
    fake.restore();
  });
});

describe('file states', () => {
  it.each([
    ['scanning', 'Checking for malware'],
    ['scan_failed', 'Could not be checked'],
    ['not_scanned', 'Not scanned'],
  ] as const)('%s reads "%s" (and in Arabic)', (state, english) => {
    const { unmount } = renderUi(<FileStateTag state={state} />);
    expect(screen.getByRole('status').textContent).toBe(english);
    unmount();
    renderUi(<FileStateTag state={state} />, { locale: 'ar' });
    expect(screen.getByRole('status').textContent).not.toBe(english);
  });
});

describe('inline images (REQ-INC-064 AC2)', () => {
  it('finds the file IDs to attach when saving', () => {
    const html =
      '<p>see</p><img data-file-id="01a17826-97b9-747c-b630-0d20263b86e9" alt="x"><img alt="y">';
    expect(inlineImageIds(html)).toEqual(['01a17826-97b9-747c-b630-0d20263b86e9']);
  });

  it('shows stored images through the files API and nothing else', () => {
    renderUi(
      <RichTextView
        html='<p><img data-file-id="01a17826-97b9-747c-b630-0d20263b86e9" alt="Pasted image"><img data-file-id="nope" alt="bad"></p>'
        testId="view"
      />,
    );
    const images = screen.getByTestId('view').querySelectorAll('img');
    expect(images[0]?.getAttribute('src')).toBe(
      '/api/v1/files/01a17826-97b9-747c-b630-0d20263b86e9/inline',
    );
    expect(images[1]?.getAttribute('src')).toBeNull();
  });
});
