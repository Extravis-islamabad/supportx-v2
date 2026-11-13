import { ArrowDownOutlined, ArrowUpOutlined, CloseOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Checkbox, Empty, Input, List, Space, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';

import type { ListColumn } from '@supportx/api-client';
import { Drawer, useLabel } from '@supportx/ui';

import { DEFAULT_COLUMNS, type ColumnContext, type ColumnSpec } from './columns';

const MAX_COLUMNS = 40;

/**
 * Choose, order and remove the list's columns (REQ-INC-104): every field by search, built-in,
 * system times and custom fields alike. Buttons move a column, so it works without dragging and
 * from the keyboard; widths change on the table header itself.
 */
export function ColumnChooser({
  columns,
  catalogue,
  context,
  onChange,
}: {
  columns: ListColumn[];
  catalogue: Map<string, ColumnSpec>;
  context: ColumnContext;
  onChange: (columns: ListColumn[]) => void;
}) {
  const t = useLabel();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const chosen = new Set(columns.map((c) => c.key));
  const name = (key: string) => catalogue.get(key)?.title(context) ?? key;
  const needle = search.trim().toLocaleLowerCase();
  const offered = [...catalogue.keys()]
    .filter((key) => !chosen.has(key))
    .filter((key) => needle === '' || name(key).toLocaleLowerCase().includes(needle))
    .sort((a, b) => name(a).localeCompare(name(b)));
  const move = (index: number, by: -1 | 1) => {
    const next = [...columns];
    const [item] = next.splice(index, 1);
    if (item === undefined) return;
    next.splice(index + by, 0, item);
    onChange(next);
  };

  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
        data-testid="inc-columns"
      >
        {t('incidents.columns.button')}
      </Button>
      <Drawer
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title={t('incidents.columns.title')}
        width={420}
        data-testid="inc-columns-drawer"
        extra={
          <Space>
            {/* Your columns stay; only their widths go back to each column's own (Haider,
                2026-11-10). */}
            <Button
              disabled={columns.every((c) => c.width == null)}
              onClick={() => {
                onChange(columns.map((c) => ({ ...c, width: null })));
              }}
              data-testid="inc-columns-reset-widths"
            >
              {t('incidents.columns.reset_widths')}
            </Button>
            <Button
              onClick={() => {
                onChange(DEFAULT_COLUMNS.map((key) => ({ key, width: null })));
              }}
              data-testid="inc-columns-reset"
            >
              {t('incidents.columns.reset')}
            </Button>
          </Space>
        }
      >
        <Typography.Title level={5}>{t('incidents.columns.shown')}</Typography.Title>
        <List
          size="small"
          dataSource={columns}
          data-testid="inc-columns-shown"
          renderItem={(column, index) => (
            <List.Item
              data-testid={`inc-column-${column.key}`}
              actions={[
                <Button
                  key="up"
                  size="small"
                  type="text"
                  icon={<ArrowUpOutlined />}
                  disabled={index === 0}
                  aria-label={t('incidents.columns.move_up', { column: name(column.key) })}
                  onClick={() => {
                    move(index, -1);
                  }}
                />,
                <Button
                  key="down"
                  size="small"
                  type="text"
                  icon={<ArrowDownOutlined />}
                  disabled={index === columns.length - 1}
                  aria-label={t('incidents.columns.move_down', { column: name(column.key) })}
                  onClick={() => {
                    move(index, 1);
                  }}
                />,
                <Button
                  key="remove"
                  size="small"
                  type="text"
                  icon={<CloseOutlined />}
                  disabled={columns.length === 1}
                  aria-label={t('incidents.columns.remove', { column: name(column.key) })}
                  onClick={() => {
                    onChange(columns.filter((c) => c.key !== column.key));
                  }}
                  data-testid={`inc-column-remove-${column.key}`}
                />,
              ]}
            >
              {name(column.key)}
            </List.Item>
          )}
        />
        <Typography.Title level={5} style={{ marginTop: 16 }}>
          {t('incidents.columns.add')}
        </Typography.Title>
        <Input.Search
          allowClear
          value={search}
          placeholder={t('incidents.columns.search')}
          aria-label={t('incidents.columns.search')}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          data-testid="inc-columns-search"
        />
        {offered.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('incidents.columns.none')} />
        ) : (
          <List
            size="small"
            dataSource={offered}
            renderItem={(key) => (
              <List.Item
                actions={[
                  <Button
                    key="add"
                    size="small"
                    icon={<PlusOutlined />}
                    disabled={columns.length >= MAX_COLUMNS}
                    aria-label={t('incidents.columns.add_one', { column: name(key) })}
                    onClick={() => {
                      onChange([...columns, { key, width: null }]);
                    }}
                    data-testid={`inc-column-add-${key}`}
                  />,
                ]}
              >
                {name(key)}
              </List.Item>
            )}
          />
        )}
      </Drawer>
    </>
  );
}

/**
 * The "select all on this page" box of the list. Ant Design copies column titles into a hidden
 * measuring row (`aria-hidden`); a copy found there is made unfocusable, so no focusable control
 * hides from screen readers (axe aria-hidden-focus).
 */
export function SelectPageBox({
  checked,
  indeterminate,
  onChange,
  label,
}: {
  checked: boolean;
  indeterminate: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const root = box.current;
    if (root?.closest('.ant-table-measure-row') == null) return;
    // The hidden copy: out of the tab order, not operable, not found by tests.
    for (const input of root.querySelectorAll('input')) {
      input.tabIndex = -1;
      input.disabled = true;
    }
    root.querySelector('[data-testid]')?.removeAttribute('data-testid');
  }, []);
  return (
    <span ref={box}>
      <Checkbox
        checked={checked}
        indeterminate={indeterminate}
        aria-label={label}
        onChange={(event) => {
          onChange(event.target.checked);
        }}
        data-testid="inc-select-page"
      />
    </span>
  );
}
