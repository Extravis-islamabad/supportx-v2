import { Extension } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';

/**
 * Per-item reading direction for lists (QA BUG-03). Every block carries `dir="auto"`, but a list
 * item whose paragraph has its own `dir` finds no text of its own, so the browser lays the item
 * (and its bullet) out left to right: Arabic items ended up with the bullet on the far side. Each
 * list item gets the direction of its first strong letter instead, and lists indent per item
 * (styles.tsx), so the bullet sits beside its text in Arabic, English and mixed lists.
 */

// Hebrew, Arabic, Syriac, Thaana, NKo, Samaritan, Mandaic, Arabic supplements and presentation forms.
const RTL = /[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]/;
const LTR = /[A-Za-z\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff]/;

/** The direction of the first strong letter, or null when there is none (digits, symbols). */
export function strongDirection(text: string): 'rtl' | 'ltr' | null {
  for (const char of text) {
    if (RTL.test(char)) return 'rtl';
    if (LTR.test(char)) return 'ltr';
  }
  return null;
}

/** Stored HTML with each list item's `dir` set from its own text (for the read-only view). */
export function withItemDirections(html: string): string {
  if (!html.includes('<li') || typeof DOMParser === 'undefined') return html;
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
  for (const item of Array.from(doc.body.querySelectorAll('li'))) {
    const direction = strongDirection(item.textContent);
    if (direction !== null) item.setAttribute('dir', direction);
  }
  return doc.body.innerHTML;
}

const KEY = new PluginKey('listItemDirection');

/** The same for the editor: a decoration sets each list item's `dir` while typing. */
export const ListItemDirection = Extension.create({
  name: 'listItemDirection',
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: KEY,
        props: {
          decorations: (state) => {
            const found: Decoration[] = [];
            state.doc.descendants((node, pos) => {
              if (node.type.name !== 'listItem') return true;
              const direction = strongDirection(node.textContent);
              if (direction !== null) {
                found.push(Decoration.node(pos, pos + node.nodeSize, { dir: direction }));
              }
              return true;
            });
            return DecorationSet.create(state.doc, found);
          },
        },
      }),
    ];
  },
});
