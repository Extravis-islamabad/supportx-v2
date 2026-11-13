import { Table } from 'antd';
import { describe, expect, it } from 'vitest';
import { waitFor } from '@testing-library/react';

import { renderUi } from './test/render';

// A selectable table that scrolls sideways copies its "select all" checkbox into the hidden
// measure row (rc-table 7.54): that row must be inert (axe aria-hidden-focus; Cluster 43313118567).
describe('table measure rows', () => {
  it('are inert, so the copied header controls are out of the focus order', async () => {
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
        expect(row.hasAttribute('inert')).toBe(true);
      });
    });
  });
});
