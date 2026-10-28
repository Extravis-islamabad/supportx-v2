import { AutoComplete, Flex, Input, Tag } from 'antd';

import type { IncidentListField } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

import type { ReportWords } from '../../reports/names';
import { chipSuggestions, type SearchChip } from './model';

// Search with chips (REQ-INC-109): the box still searches subjects and IDs as you type; its
// suggestions add "field is value" chips chosen from the field's own values, so nobody has to
// learn a syntax (AC2). Chips narrow the list in place; the page never changes (AC3).

export function SearchChips({
  text,
  onText,
  chips,
  onChips,
  fields,
  words,
}: {
  text: string;
  onText: (text: string) => void;
  chips: SearchChip[];
  onChips: (chips: SearchChip[]) => void;
  fields: IncidentListField[];
  words: ReportWords;
}) {
  const t = useLabel();
  const suggestions = chipSuggestions(text, fields, words, t, chips);
  return (
    <Flex gap={8} wrap align="center" style={{ minWidth: 0 }}>
      <AutoComplete
        value={text}
        onChange={onText}
        options={suggestions.map((chip) => ({
          value: `${chip.field}\u0000${chip.value}`,
          label: chip.label,
        }))}
        onSelect={(picked: string) => {
          const chip = suggestions.find((c) => `${c.field}\u0000${c.value}` === picked);
          if (chip !== undefined) onChips([...chips, chip]);
          onText('');
        }}
        style={{ width: 320, maxWidth: '100%' }}
      >
        <Input.Search
          allowClear
          aria-label={t('incidents.search')}
          placeholder={t('incidents.search_chips')}
          data-testid="inc-search"
        />
      </AutoComplete>
      {chips.map((chip) => (
        <Tag
          key={`${chip.field}:${chip.value}`}
          closable
          onClose={() => {
            onChips(chips.filter((c) => c !== chip));
          }}
          data-testid={`inc-chip-${chip.field}-${chip.value}`}
        >
          {chip.label}
        </Tag>
      ))}
    </Flex>
  );
}
