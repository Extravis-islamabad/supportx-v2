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
}
