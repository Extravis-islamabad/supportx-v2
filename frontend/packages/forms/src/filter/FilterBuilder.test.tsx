import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { LabelsProvider } from '@supportx/labels';

import { FilterBuilder } from './FilterBuilder';
import { rowProblems, type FilterFieldOption, type FilterModel } from './model';

const FIELDS: FilterFieldOption[] = [
  {
    name: 'priority',
    type: 'enum',
    label: 'Priority',
    choices: [
      { value: 'p1', label: 'P1 - Critical' },
      { value: 'p2', label: 'P2 - High' },
    ],
  },
  { name: 'subject', type: 'string', label: 'Subject' },
];

function Harness({ onModel }: { onModel: (model: FilterModel) => void }) {
  const [model, setModel] = useState<FilterModel>({ join: 'and', rows: [] });
  return (
    <LabelsProvider locale="en">
      <FilterBuilder
        fields={FIELDS}
        value={model}
        onChange={(next) => {
          setModel(next);
          onModel(next);
        }}
      />
    </LabelsProvider>
  );
}

describe('FilterBuilder', () => {
  it('adds a condition, names its field and says a value is missing', () => {
    let latest: FilterModel = { join: 'and', rows: [] };
    render(
      <Harness
        onModel={(model) => {
          latest = model;
        }}
      />,
    );
    expect(screen.getByText('No conditions: every record you may see.')).toBeDefined();
    fireEvent.click(screen.getByTestId('filter-add'));
    expect(latest.rows).toEqual([{ field: 'priority', op: 'in', value: [] }]);
    expect(screen.getByRole('alert').textContent).toBe('Enter a value, or remove this condition.');
    expect(rowProblems(latest).size).toBe(1);
    expect(screen.getByText('Priority')).toBeDefined();
    expect(screen.getByText('is one of')).toBeDefined();
    fireEvent.click(screen.getByTestId('filter-remove-0'));
    expect(latest.rows).toEqual([]);
  });
});
