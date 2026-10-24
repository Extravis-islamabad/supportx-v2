import { RichTextStyles } from './styles';

/**
 * Stored rich text, read-only. The HTML comes from the API, which sanitised it with the
 * allow-list on save (backend/app/shared/richtext.py, nh3): the server is the security boundary,
 * the browser only renders it.
 */
export function RichTextView({ html, testId }: { html: string | null; testId?: string }) {
  if (html === null || html === '') return null;
  return (
    <>
      <RichTextStyles />
      <div
        className="sx-richtext"
        dir="auto"
        data-testid={testId}
        // Server-sanitised HTML (see above); React would otherwise show the tags as text.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </>
  );
}
