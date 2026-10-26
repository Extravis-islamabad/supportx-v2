import { Select } from 'antd';
import { useState } from 'react';

/**
 * Free tags (Enter or comma adds one). The suggestion list is open only while something is
 * typed, so it never stays over the buttons below after a tag is added (QA C6).
 */
export function TagsInput({
  id,
  value,
  onChange,
  ariaLabel,
  testId,
}: {
  id?: string;
  value: string[];
  onChange: (next: string[]) => void;
  ariaLabel?: string;
  testId: string;
}) {
  const [search, setSearch] = useState('');
  return (
    <Select
      id={id}
      mode="tags"
      aria-label={ariaLabel}
      value={value}
      searchValue={search}
      onSearch={setSearch}
      open={search !== ''}
      onChange={(next: string[]) => {
        setSearch('');
        onChange(next);
      }}
      tokenSeparators={[',']}
      style={{ width: '100%' }}
      data-testid={testId}
    />
  );
}
