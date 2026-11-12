import { render, waitFor } from '@testing-library/react';
import { Form, Select, TreeSelect } from 'antd';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { AppearanceProvider } from './AppearanceProvider';

// Matrix run 42978769692 (axe aria-allowed-attr on the article's topic): a required select's
// outer box loses `aria-required`; its combobox input keeps it, so "required" is still said.

function Fields() {
  const [shown, setShown] = useState(false);
  return (
    <Form>
      <Form.Item label="Topic" name="topic" rules={[{ required: true }]}>
        <TreeSelect treeData={[]} data-testid="topic" />
      </Form.Item>
      <button
        type="button"
        onClick={() => {
          setShown(true);
        }}
      >
        more
      </button>
      {shown && (
        <Form.Item label="Type" name="type" rules={[{ required: true }]}>
          <Select options={[]} data-testid="type" />
        </Form.Item>
      )}
    </Form>
  );
}

describe('a required select (axe aria-allowed-attr)', () => {
  it('keeps aria-required on its input only, also for one drawn later', async () => {
    const view = render(
      <AppearanceProvider initialMode="light">
        <Fields />
      </AppearanceProvider>,
    );
    const box = (id: string) => view.getByTestId(id);
    await waitFor(() => {
      expect(box('topic').hasAttribute('aria-required')).toBe(false);
    });
    expect(box('topic').querySelector('input')?.getAttribute('aria-required')).toBe('true');
    view.getByText('more').click();
    await waitFor(() => {
      expect(box('type').hasAttribute('aria-required')).toBe(false);
    });
    expect(box('type').querySelector('input')?.getAttribute('aria-required')).toBe('true');
  });
});
