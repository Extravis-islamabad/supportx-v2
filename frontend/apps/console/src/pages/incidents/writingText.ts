// Plain text in and out of the editor for writing help (WP-038).

/** The text of the editor's HTML, for the improve mode. */
export function plainText(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  return doc.body.textContent.trim();
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
