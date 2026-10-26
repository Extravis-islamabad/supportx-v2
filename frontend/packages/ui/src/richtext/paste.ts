/**
 * Clean pasted HTML before the editor reads it (WP-020b): Word, Outlook and web pages bring
 * styles, fonts, classes, conditional comments and Office-only tags. What survives is structure
 * the editor knows: paragraphs, headings, lists, tables, links, bold, italic, underline and
 * strike. Word's fake lists (paragraphs with a typed bullet) become real lists, and centred or
 * justified paragraphs keep their alignment as a code. Fonts, sizes and colours never come in:
 * the palette is fixed. The server sanitises again before storing (the security boundary).
 *
 * Images inside pasted HTML are dropped here (remote addresses are never stored). Image *files*
 * pasted or dropped into the editor are uploaded as drafts and shown inline (inlineImage.tsx).
 */

const DROP = 'style, meta, link, title, script, xml, template, img, picture, svg, object, iframe';
const UNWRAP = new Set(['FONT', 'SPAN', 'DIV', 'SECTION', 'ARTICLE', 'HEADER', 'FOOTER', 'MAIN']);
const KEEP_ATTRIBUTES: Record<string, string[]> = {
  A: ['href'],
  TD: ['colspan', 'rowspan'],
  TH: ['colspan', 'rowspan'],
  OL: ['start'],
};
// Office's own tags (o:p, w:sdt, v:shape ...) carry no content worth keeping as structure.
const OFFICE_TAG = /^[a-z]+:/i;
const BULLET_TEXT =
  /^[\s\u00a0]*([\u00b7\u2022\u25aa\u25cf\u25e6o\u00a7\-\u2013*]|\d+[.)]|[a-z][.)]|[ivx]+[.)])[\s\u00a0]*$/i;
const ORDERED_TEXT = /^[\s\u00a0]*(\d+|[a-z]|[ivx]+)[.)][\s\u00a0]*$/i;

function listLevel(element: Element): number | null {
  const style = element.getAttribute('style') ?? '';
  const level = /mso-list:\s*l\d+\s+level(\d+)/i.exec(style);
  const found = level?.[1];
  if (found !== undefined) return Number(found);
  return /MsoListParagraph/i.test(element.getAttribute('class') ?? '') ? 1 : null;
}

/** Word marks a list paragraph's bullet as `mso-list:Ignore`; take it out and say its kind. */
function takeBullet(element: Element): 'ul' | 'ol' {
  let ordered = false;
  for (const marker of Array.from(element.querySelectorAll('[style*="mso-list"]'))) {
    if (/mso-list:\s*ignore/i.test(marker.getAttribute('style') ?? '')) {
      ordered = ORDERED_TEXT.test(marker.textContent);
      marker.remove();
    }
  }
  // Without the marker span (Outlook, some versions): a typed bullet at the start of the text.
  const first = element.firstChild;
  if (first?.nodeType === Node.TEXT_NODE) {
    const text = first.textContent ?? '';
    const match = /^[\s\u00a0]*(\S+)[\s\u00a0]+/.exec(text);
    if (match?.[1] !== undefined && BULLET_TEXT.test(match[1])) {
      ordered = ORDERED_TEXT.test(match[1]);
      first.textContent = text.slice(match[0].length);
    }
  }
  return ordered ? 'ol' : 'ul';
}

/** Consecutive Word list paragraphs → nested <ul>/<ol> with <li>. */
function rebuildWordLists(body: HTMLElement): void {
  const doc = body.ownerDocument;
  const paragraphs = Array.from(body.querySelectorAll('p'));
  let stack: { level: number; list: HTMLElement }[] = [];
  // The last list paragraph seen: a list continues only on the very next paragraph.
  let previous = null as Element | null;
  for (const paragraph of paragraphs) {
    const level = listLevel(paragraph);
    if (level === null) {
      stack = [];
      previous = null;
      continue;
    }
    if (previous?.nextElementSibling !== paragraph) stack = [];
    const kind = takeBullet(paragraph);
    const item = doc.createElement('li');
    const inner = doc.createElement('p');
    while (paragraph.firstChild) inner.appendChild(paragraph.firstChild);
    item.appendChild(inner);
    while (stack.length > 0 && (stack.at(-1)?.level ?? 0) > level) stack.pop();
    const top = stack.at(-1);
    if (top === undefined || top.level < level) {
      const list = doc.createElement(kind);
      if (top === undefined) paragraph.before(list);
      else (top.list.lastElementChild ?? top.list).appendChild(list);
      stack.push({ level, list });
    }
    stack.at(-1)?.list.appendChild(item);
    previous = paragraph;
    // Keep the empty paragraph in place until the next one is checked for adjacency.
    paragraph.setAttribute('data-sx-remove', '');
    paragraph.style.display = 'none';
  }
  for (const done of Array.from(body.querySelectorAll('[data-sx-remove]'))) done.remove();
}

function alignmentOf(element: Element): string | null {
  const style = (element.getAttribute('style') ?? '').toLowerCase();
  const align = (element.getAttribute('align') ?? '').toLowerCase();
  if (style.includes('text-align:center') || style.includes('text-align: center')) return 'center';
  if (style.includes('text-align:justify') || style.includes('text-align: justify')) {
    return 'justify';
  }
  if (align === 'center' || align === 'justify') return align;
  return null; // left and right depend on the reading direction: leave them to it
}

function rename(element: Element, tag: string): Element {
  const next = element.ownerDocument.createElement(tag);
  while (element.firstChild) next.appendChild(element.firstChild);
  element.replaceWith(next);
  return next;
}

function unwrap(element: Element): void {
  element.replaceWith(...Array.from(element.childNodes));
}

function clean(element: Element): void {
  for (const child of Array.from(element.children)) clean(child);
  const tag = element.tagName.toUpperCase();
  if (OFFICE_TAG.test(element.tagName)) {
    if (element.textContent.trim() === '') element.remove();
    else unwrap(element);
    return;
  }
  let target: Element = element;
  if (tag === 'B') target = rename(element, 'strong');
  else if (tag === 'I') target = rename(element, 'em');
  else if (tag === 'STRIKE' || tag === 'DEL') target = rename(element, 's');
  else if (tag === 'H1') target = rename(element, 'h2');
  else if (tag === 'H5' || tag === 'H6') target = rename(element, 'h4');
  const align = ['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6'].includes(tag)
    ? alignmentOf(element)
    : null;
  const keep = KEEP_ATTRIBUTES[target.tagName.toUpperCase()] ?? [];
  for (const attribute of Array.from(target.attributes)) {
    if (!keep.includes(attribute.name)) target.removeAttribute(attribute.name);
  }
  if (align !== null) target.setAttribute('data-align', align);
  if (UNWRAP.has(target.tagName.toUpperCase())) unwrap(target);
}

/** The cleaned HTML of a paste (see above). Plain text pastes never come through here. */
export function cleanPastedHtml(html: string): string {
  const withoutComments = html
    .replace(/<!--\[if[\s\S]*?<!\[endif\]-->/gi, '')
    .replace(/<!--[\s\S]*?-->/g, '');
  const doc = new DOMParser().parseFromString(withoutComments, 'text/html');
  const body = doc.body;
  for (const element of Array.from(body.querySelectorAll(DROP))) element.remove();
  rebuildWordLists(body);
  for (const child of Array.from(body.children)) clean(child);
  // Word puts &nbsp;-only paragraphs between blocks for spacing.
  for (const paragraph of Array.from(body.querySelectorAll('p'))) {
    if (
      paragraph.textContent.replace(/\u00a0/g, ' ').trim() === '' &&
      paragraph.querySelector('br, a, strong, em') === null
    ) {
      paragraph.remove();
    }
  }
  return body.innerHTML;
}
