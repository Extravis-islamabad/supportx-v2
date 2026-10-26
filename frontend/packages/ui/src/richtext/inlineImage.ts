import { Image } from '@tiptap/extension-image';
import type { EditorView } from '@tiptap/pm/view';
import { ReactNodeViewRenderer } from '@tiptap/react';

import { uploadFile, type FileRules, type StoredFile } from '@supportx/api-client';
import type { LabelInput, LabelParams } from '@supportx/labels';

import { describeError } from '../errors';
import { refusal } from '../files/useUploads';
import { InlineImageView } from './InlineImageView';

/**
 * Images inside rich text (WP-022, REQ-INC-064 AC2; replaces the WP-020b placeholder).
 *
 * A pasted or dropped screenshot is uploaded as the author's draft file; the node keeps only the
 * file's ID (`<img data-file-id alt>`, the only image the server's sanitiser keeps). Its `src` is
 * never stored: the image comes from the files API, which checks the reader's access and the scan
 * state, so the node shows "uploading", then "checking", then the image (or "blocked"). When the
 * entry is saved, the screen attaches the drafts to it (`attachDrafts`).
 */
export const InlineImage = Image.extend({
  addAttributes() {
    return {
      fileId: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute('data-file-id'),
        renderHTML: (attributes: Record<string, unknown>) =>
          typeof attributes.fileId === 'string' ? { 'data-file-id': attributes.fileId } : {},
      },
      alt: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute('alt'),
        renderHTML: (attributes: Record<string, unknown>) =>
          typeof attributes.alt === 'string' ? { alt: attributes.alt } : {},
      },
      // While uploading: which upload this node waits for (never rendered or stored).
      uploadKey: { default: null, rendered: false },
      failed: { default: null, rendered: false },
    };
  },
  parseHTML() {
    return [{ tag: 'img[data-file-id]' }];
  },
  addNodeView() {
    return ReactNodeViewRenderer(InlineImageView);
  },
}).configure({ inline: false, allowBase64: false });

type Translate = (key: LabelInput, params?: LabelParams) => string;

export interface ImageUploadContext {
  ownerId: string;
  rules: FileRules | undefined;
  t: Translate;
  onStored?: (file: StoredFile) => void;
}

function setAttrs(view: EditorView, key: string, attrs: Record<string, unknown>): void {
  view.state.doc.descendants((child, pos) => {
    if (child.type.name === 'image' && child.attrs.uploadKey === key) {
      view.dispatch(view.state.tr.setNodeMarkup(pos, undefined, { ...child.attrs, ...attrs }));
      return false;
    }
    return true;
  });
}

/**
 * Insert one placeholder per image at `pos` and upload each as a draft; the placeholder becomes
 * the stored file when the upload answers (or says why it failed). True when it took the files.
 */
export function insertImages(
  view: EditorView,
  files: File[],
  pos: number,
  context: ImageUploadContext,
): boolean {
  const images = files.filter((file) => file.type.startsWith('image/'));
  if (images.length === 0) return false;
  const imageType = view.state.schema.nodes.image;
  if (imageType === undefined) return false;
  let at = pos;
  for (const image of images) {
    const key = crypto.randomUUID();
    const refused = refusal(image, context.rules, context.t);
    const node = imageType.create({
      uploadKey: key,
      alt: context.t('richtext.image_alt'),
      failed: refused,
    });
    view.dispatch(view.state.tr.insert(at, node));
    at += node.nodeSize;
    if (refused !== null) continue;
    uploadFile(image, { ownerType: 'draft', ownerId: context.ownerId, inline: true })
      .done.then((stored) => {
        setAttrs(view, key, { fileId: stored.id, uploadKey: null });
        context.onStored?.(stored);
      })
      .catch((error: unknown) => {
        setAttrs(view, key, { failed: describeError(error, context.t).title });
      });
  }
  return true;
}

/** File IDs of the inline images in editor HTML (to attach the drafts when saving). */
export function inlineImageIds(html: string): string[] {
  return [...html.matchAll(/<img[^>]*\bdata-file-id="([0-9a-fA-F-]{36})"/g)].flatMap((m) =>
    m[1] === undefined ? [] : [m[1]],
  );
}
