import { Extension, Mark, mergeAttributes, type CommandProps } from '@tiptap/core';

/**
 * Editor extensions of our own (WP-020b). Everything is stored as codes in `data-*` attributes,
 * never inline styles: the server's allow-list (backend/app/shared/richtext.py) keeps exactly
 * these codes, and the theme decides the real colours (light, dark, high contrast) so text stays
 * readable. No free font, size or colour exists.
 */

// The fixed palettes; the same codes as TEXT_COLOURS / HIGHLIGHTS on the server.
export const TEXT_COLOURS = ['brand', 'red', 'orange', 'green', 'blue', 'grey'] as const;
export const HIGHLIGHTS = ['yellow', 'green', 'blue', 'pink'] as const;
export type TextColour = (typeof TEXT_COLOURS)[number];
export type HighlightColour = (typeof HIGHLIGHTS)[number];
// Logical alignment: "start" is left in English and right in Arabic, so it is right in both.
export const ALIGNMENTS = ['start', 'center', 'end', 'justify'] as const;
export type Alignment = (typeof ALIGNMENTS)[number];
export const MAX_INDENT = 6;

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    blockFormat: {
      setAlignment: (alignment: Alignment | null) => ReturnType;
      indent: () => ReturnType;
      outdent: () => ReturnType;
    };
    textColour: {
      setTextColour: (colour: TextColour) => ReturnType;
      unsetTextColour: () => ReturnType;
    };
    highlightColour: {
      setHighlight: (colour: HighlightColour) => ReturnType;
      unsetHighlight: () => ReturnType;
    };
  }
}

const BLOCKS = ['paragraph', 'heading'];

function oneOf<T extends string>(values: readonly T[], value: string | null): T | null {
  return value !== null && (values as readonly string[]).includes(value) ? (value as T) : null;
}

/** Alignment and indent of paragraphs and headings (`data-align`, `data-indent`). */
export const BlockFormat = Extension.create({
  name: 'blockFormat',
  addGlobalAttributes() {
    return [
      {
        types: BLOCKS,
        attributes: {
          align: {
            default: null,
            parseHTML: (element) => oneOf(ALIGNMENTS, element.getAttribute('data-align')),
            renderHTML: (attributes) =>
              attributes.align ? { 'data-align': attributes.align as string } : {},
          },
          indent: {
            default: 0,
            parseHTML: (element) => {
              const value = Number(element.getAttribute('data-indent') ?? '0');
              return Number.isInteger(value) && value > 0 ? Math.min(value, MAX_INDENT) : 0;
            },
            renderHTML: (attributes) =>
              (attributes.indent as number) > 0
                ? { 'data-indent': String(attributes.indent as number) }
                : {},
          },
        },
      },
    ];
  },
  addCommands() {
    const change =
      (delta: number) =>
      ({ tr, state, dispatch }: CommandProps): boolean => {
        const moved: number[] = [];
        state.doc.nodesBetween(state.selection.from, state.selection.to, (node, pos) => {
          if (!BLOCKS.includes(node.type.name)) return;
          const current = (node.attrs.indent as number | undefined) ?? 0;
          const next = Math.max(0, Math.min(MAX_INDENT, current + delta));
          if (next !== current) {
            tr.setNodeMarkup(pos, undefined, { ...node.attrs, indent: next });
            moved.push(pos);
          }
        });
        if (moved.length > 0 && dispatch) dispatch(tr);
        return moved.length > 0;
      };
    return {
      setAlignment:
        (alignment) =>
        ({ commands }) =>
          BLOCKS.map((type) => commands.updateAttributes(type, { align: alignment })).some(Boolean),
      indent: () => change(1),
      outdent: () => change(-1),
    };
  },
});

/** Text colour from the fixed palette: `<span data-color="red">`. */
export const TextColourMark = Mark.create({
  name: 'textColour',
  addAttributes() {
    return {
      colour: {
        default: null,
        parseHTML: (element) => oneOf(TEXT_COLOURS, element.getAttribute('data-color')),
        renderHTML: (attributes) => ({ 'data-color': attributes.colour as string }),
      },
    };
  },
  parseHTML() {
    return [
      {
        tag: 'span[data-color]',
        getAttrs: (element) =>
          oneOf(TEXT_COLOURS, element.getAttribute('data-color')) ? null : false,
      },
    ];
  },
  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(HTMLAttributes), 0];
  },
  addCommands() {
    return {
      setTextColour:
        (colour) =>
        ({ commands }) =>
          commands.setMark(this.name, { colour }),
      unsetTextColour:
        () =>
        ({ commands }) =>
          commands.unsetMark(this.name),
    };
  },
});

/** Highlight from the fixed palette: `<mark data-color="yellow">`. */
export const HighlightMark = Mark.create({
  name: 'highlightColour',
  addAttributes() {
    return {
      colour: {
        default: 'yellow',
        parseHTML: (element) => oneOf(HIGHLIGHTS, element.getAttribute('data-color')) ?? 'yellow',
        renderHTML: (attributes) => ({ 'data-color': attributes.colour as string }),
      },
    };
  },
  parseHTML() {
    return [{ tag: 'mark' }];
  },
  renderHTML({ HTMLAttributes }) {
    return ['mark', mergeAttributes(HTMLAttributes), 0];
  },
  addCommands() {
    return {
      setHighlight:
        (colour) =>
        ({ commands }) =>
          commands.setMark(this.name, { colour }),
      unsetHighlight:
        () =>
        ({ commands }) =>
          commands.unsetMark(this.name),
    };
  },
});
