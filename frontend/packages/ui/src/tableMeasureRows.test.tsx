import { Table } from 'antd';
import { describe, expect, it } from 'vitest';
import { waitFor } from '@testing-library/react';

import { renderUi } from './test/render';

// A selectable table that scrolls sideways copies its "select all" checkbox into the hidden
// measure row (rc-table 7.54): the copy is out of the tab order (axe aria-hidden-focus; Cluster
// 43313118567), while the row itself keeps its own tabindex for axe's scrollable-region-focusable
// on a table with no rows (Stack smoke 43360374564).
describe('table measure rows', () => {
  it('keep their copied controls out of the tab order, and the row itself as it was', async () => {
    const { container } = renderUi(
      <Table
        rowKey="id"
        dataSource={[{ id: '1', name: 'One' }]}
        columns={[{ key: 'name', dataIndex: 'name', title: 'Name' }]}
        rowSelection={{ selectedRowKeys: [], onChange: () => undefined }}
        scroll={{ x: 1200 }}
        pagination={false}
      />,
    );
    await waitFor(() => {
      const rows = container.querySelectorAll('.ant-table-measure-row');
      expect(rows.length).toBeGreaterThan(0);
      rows.forEach((row) => {
        expect(row.hasAttribute('inert')).toBe(false);
        expect(row.getAttribute('tabindex')).toBe('-1');
        const controls = row.querySelectorAll('input, button, a[href]');
        expect(controls.length).toBeGreaterThan(0); // the copied select-all checkbox
        controls.forEach((control) => {
          expect(control.getAttribute('tabindex')).toBe('-1');
        });
      });
    });
  });
});
