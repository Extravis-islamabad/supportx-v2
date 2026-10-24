import { Skeleton } from 'antd';
import { lazy, Suspense } from 'react';

import type { RichTextFieldProps } from './types';

// The editor and ProseMirror load only when a form shows a rich-text field (§9.2 code splitting).
const RichTextEditor = lazy(() => import('./RichTextEditor'));

/** Rich-text input (Tiptap, lazy). Value in and out is HTML; the server sanitises it (D-051). */
export function RichTextField(props: RichTextFieldProps) {
  return (
    <Suspense fallback={<Skeleton.Input active block style={{ height: 180 }} />}>
      <RichTextEditor {...props} />
    </Suspense>
  );
}
