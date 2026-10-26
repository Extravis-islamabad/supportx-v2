import { useEffect, useRef } from 'react';

import { fileImageUrl } from '@supportx/api-client';

import { RichTextStyles } from './styles';

const FILE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Stored rich text, read-only. The HTML comes from the API, which sanitised it with the
 * allow-list on save (backend/app/shared/richtext.py, nh3): the server is the security boundary,
 * the browser only renders it.
 *
 * Inline images (WP-022) are stored as file IDs only. Their address is filled in here: the files
 * API checks the reader's access and the scan state. An image that cannot be shown (not yet
 * checked, blocked, or not visible to this reader) shows its description instead.
 */
export function RichTextView({ html, testId }: { html: string | null; testId?: string }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = container.current;
    if (root === null) return;
    for (const image of root.querySelectorAll<HTMLImageElement>('img[data-file-id]')) {
      const id = image.dataset.fileId ?? '';
      if (!FILE_ID.test(id) || image.getAttribute('src') !== null) continue;
      image.loading = 'lazy';
      image.onerror = () => {
        const text = document.createElement('span');
        text.className = 'sx-inline-image-missing';
        text.textContent = image.alt;
        image.replaceWith(text);
      };
      image.src = fileImageUrl(id, 'inline');
    }
  }, [html]);
  if (html === null || html === '') return null;
  return (
    <>
      <RichTextStyles />
      <div
        ref={container}
        className="sx-richtext"
        dir="auto"
        data-testid={testId}
        // Server-sanitised HTML (see above); React would otherwise show the tags as text.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </>
  );
}
