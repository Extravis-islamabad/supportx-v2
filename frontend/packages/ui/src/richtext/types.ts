import type { MentionSearch } from './mention';

/** A text to insert at the caret (reply templates, REQ-INC-058). */
export interface RichTextTemplate {
  id: string;
  name: string;
  /** Sanitised rich text (HTML) from the server. */
  body: string;
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
}
