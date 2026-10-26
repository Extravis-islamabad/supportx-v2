import { Mention } from '@tiptap/extension-mention';
import { ReactRenderer } from '@tiptap/react';

import { MentionList, type ListHandle, type ListProps } from './MentionList';

/** A person to mention: their name, the email that tells two people apart, and access. */
export interface MentionCandidate {
  id: string;
  label: string;
  email: string;
  /** False: they cannot see the record, so a mention notifies nobody (REQ-INC-063 AC2). */
  canSee: boolean;
}

export type MentionSearch = (query: string) => Promise<MentionCandidate[]>;

function place(element: HTMLElement, rect: (() => DOMRect | null) | null | undefined): void {
  const box = rect?.();
  if (box === null || box === undefined) return;
  element.style.position = 'fixed';
  element.style.zIndex = '2000';
  element.style.top = `${String(box.bottom + 4)}px`;
  // Logical start: under the caret in either reading direction, kept on screen.
  const left = Math.min(box.left, window.innerWidth - 370);
  element.style.left = `${String(Math.max(8, left))}px`;
}

/**
 * @mentions (REQ-INC-063): `@` opens a list of people from `search`; the result is stored as
 * `<span data-type="mention" data-id="…" data-label="…">@Name</span>`, which the server keeps
 * (and reads to notify and add followers).
 */
export function mentionExtension(search: MentionSearch) {
  // canSee (D-081): known when the person was picked; the composer warns before sending a mention
  // of someone who cannot see the record. Shown in the editor's HTML as data-can-see="false" only
  // (the composer removes it before sending; the server's allow-list never keeps it).
  return Mention.extend({
    addAttributes() {
      return {
        ...this.parent?.(),
        canSee: {
          default: true,
          parseHTML: (element: HTMLElement) => element.getAttribute('data-can-see') !== 'false',
          renderHTML: () => ({}),
        },
      };
    },
  }).configure({
    renderHTML: ({ node }) => [
      'span',
      {
        'data-type': 'mention',
        'data-id': node.attrs.id as string,
        'data-label': node.attrs.label as string,
        ...(node.attrs.canSee === false ? { 'data-can-see': 'false' } : {}),
      },
      `@${String(node.attrs.label ?? node.attrs.id)}`,
    ],
    suggestion: {
      items: ({ query }) => search(query),
      render: () => {
        let renderer: ReactRenderer<ListHandle, ListProps> | null = null;
        return {
          onStart: (props) => {
            renderer = new ReactRenderer(MentionList, { props, editor: props.editor });
            document.body.appendChild(renderer.element);
            place(renderer.element, props.clientRect);
          },
          onUpdate: (props) => {
            renderer?.updateProps(props);
            if (renderer !== null) place(renderer.element, props.clientRect);
          },
          onKeyDown: (props) => {
            if (props.event.key === 'Escape') {
              renderer?.element.remove();
              return true;
            }
            return renderer?.ref?.onKeyDown(props) ?? false;
          },
          onExit: () => {
            renderer?.element.remove();
            renderer?.destroy();
            renderer = null;
          },
        };
      },
    },
  });
}
