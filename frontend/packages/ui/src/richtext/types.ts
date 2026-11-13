import type { ReactNode } from 'react';

import type { MentionSearch } from './mention';

/** A text to insert at the caret (reply templates, REQ-INC-058). */
export interface RichTextTemplate {
  id: string;
  name: string;
  /** Sanitised rich text (HTML) from the server. */
  body: string;
  /**
   * The text to insert, filled for this record by the server (variables, the reader's
   * language; WP-046a S5a). Inserted instead of `body` when given; nothing when it gives ''
   * or fails. Same trust as `body`: server-sanitised HTML on the editor's allow-list, each
   * variable's value escaped as text, never markup.
   */
  fill?: () => Promise<string>;
}

export interface RichTextFieldProps {
  /** Rich text as HTML ('' or null when empty). */
  value?: string | null;
  onChange?: (html: string) => void;
  placeholder?: string;
  /** Accessible name of the editing area. */
  label: string;
  disabled?: boolean;
  invalid?: boolean;
  testId?: string;
  id?: string;
  /** People to @mention; without it `@` is plain text. */
  mentions?: MentionSearch;
  /** Reply templates offered in the toolbar (inserted at the caret). */
  templates?: RichTextTemplate[];
  /** Opens the screen where templates are managed (shown in the templates menu if given). */
  onManageTemplates?: () => void;
  /** Taller editing area (composer) or the default. */
  minHeight?: number;
  autoFocus?: boolean;
  /**
   * Images pasted or dropped into the text are uploaded as this user's draft files (WP-022) and
   * shown inline; the screen attaches them to the saved entry. Without it images are not taken.
   */
  imageOwnerId?: string;
  /** Offer callout boxes (info, warning, tip, note) in the toolbar (knowledge articles). */
  callouts?: boolean;
  /**
   * Which tools the toolbar offers: `full` (the default) or `basic`, a requester's (the portal,
   * QA 2026-11-12 F-09): text, lists, links and a quote; no code, table or horizontal line.
   * The toolbar only, never a security boundary: the server's sanitiser still accepts the full
   * set (D-051), so nothing may rely on `basic` to keep content out. Typed shortcuts still
   * work under `basic` (``` for a code block, --- for a line), as the toolbar is all it trims.
   */
  toolbar?: 'full' | 'basic';
  /**
   * More toolbar controls from the screen (the knowledge picker, D-121). They get `insert`, which
   * puts sanitised HTML at the editor's own caret; the editor keeps its state and logic.
   */
  extraTools?: (insert: (html: string) => void) => ReactNode;
}
