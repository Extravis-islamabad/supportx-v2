import type { InputProps } from 'antd';

type CountConfig = NonNullable<InputProps['count']>;

/**
 * A length limit that never changes what was typed or pasted (QA WP-026 BUG-03). Ant Design's
 * `maxLength` blocks typing and cuts pasted text without a word; this counts instead: the
 * counter shows (in red) once the text is longer than `max`, or always with `always`, and the
 * form's own check or the server refuses the save with a message at the field.
 */
export function lengthLimit(max: number, always = false): CountConfig {
  return {
    max,
    show: always ? true : ({ count }) => (count > max ? `${String(count)} / ${String(max)}` : null),
  };
}
