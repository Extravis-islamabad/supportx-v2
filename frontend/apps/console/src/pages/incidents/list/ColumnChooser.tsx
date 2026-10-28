import { ArrowDownOutlined, ArrowUpOutlined, CloseOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Drawer, Empty, Flex, Input, List, Typography } from 'antd';
import {
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ThHTMLAttributes,
} from 'react';

import type { ListColumn } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

import { DEFAULT_COLUMNS, type ColumnContext, type ColumnSpec } from './columns';

const MAX_COLUMNS = 40;
const MIN_WIDTH = 60;
const MAX_WIDTH = 800;
const KEY_STEP = 20;

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
          <Button
            onClick={() => {
              onChange(DEFAULT_COLUMNS.map((key) => ({ key, width: null })));
            }}
            data-testid="inc-columns-reset"
          >
            {t('incidents.columns.reset')}
          </Button>
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

type HeaderProps = ThHTMLAttributes<HTMLTableCellElement> & {
  width?: number;
  onResize?: (width: number) => void;
  resizeLabel?: string;
};

/**
 * A header cell whose right edge (left in RTL) drags to resize; the handle also takes the arrow
 * keys, so a width can be changed without a mouse.
 */
export function ResizableHeader({ width, onResize, resizeLabel, children, ...rest }: HeaderProps) {
  const start = useRef<{ x: number; width: number } | null>(null);
  if (onResize === undefined || width === undefined) return <th {...rest}>{children}</th>;
  const clamp = (value: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(value)));
  const rtl = () => document.documentElement.dir === 'rtl';
  const onMouseDown = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation(); // never a sort click
    start.current = { x: event.clientX, width };
    const moved = (move: globalThis.MouseEvent) => {
      if (start.current === null) return;
      const delta = (move.clientX - start.current.x) * (rtl() ? -1 : 1);
      onResize(clamp(start.current.width + delta));
    };
    const up = () => {
      start.current = null;
      window.removeEventListener('mousemove', moved);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', moved);
    window.addEventListener('mouseup', up);
  };
  const onKeyDown = (event: KeyboardEvent) => {
    const wider = rtl() ? 'ArrowLeft' : 'ArrowRight';
    const narrower = rtl() ? 'ArrowRight' : 'ArrowLeft';
    if (event.key !== wider && event.key !== narrower) return;
    event.preventDefault();
    event.stopPropagation();
    onResize(clamp(width + (event.key === wider ? KEY_STEP : -KEY_STEP)));
  };
  return (
    <th {...rest} style={{ ...rest.style, position: 'relative' }}>
      {children}
      <Flex
        role="separator"
        aria-orientation="vertical"
        aria-label={resizeLabel}
        aria-valuenow={width}
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        tabIndex={0}
        onMouseDown={onMouseDown}
        onKeyDown={onKeyDown}
        onClick={(event) => {
          event.stopPropagation();
        }}
        style={{
          position: 'absolute',
          insetBlock: 0,
          insetInlineEnd: -4,
          width: 8,
          cursor: 'col-resize',
          zIndex: 1,
        }}
      />
    </th>
  );
}
