// Plain text in and out of the editor for writing help (WP-038).

/** The text of the editor's HTML, for the improve mode. */
// Elements that end a run of words: their text must not run into the next (QA-2026-11-11 V-16,
// "…MFA device.Still…" from two paragraphs).
const BREAKS = 'p, div, li, br, h1, h2, h3, h4, h5, h6, blockquote, pre, tr, td, th';

export function plainText(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  for (const block of doc.body.querySelectorAll(BREAKS)) block.after(' ');
  return doc.body.textContent.replace(/\s+/g, ' ').trim();
}

/** The model's plain text as safe paragraphs for the editor (escaped, never raw HTML). */
export function asParagraphs(text: string): string {
  const escape = (value: string) =>
    value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  return text
    .split(/\n{2,}/)
    .map((block) => `<p>${escape(block.trim()).replaceAll('\n', '<br>')}</p>`)
    .join('');
}
