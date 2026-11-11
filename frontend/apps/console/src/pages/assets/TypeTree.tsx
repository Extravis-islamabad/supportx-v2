import { CaretDownOutlined, CaretLeftOutlined, CaretRightOutlined } from '@ant-design/icons';
import { theme, Typography } from 'antd';
import { useMemo, useRef, useState, type KeyboardEvent } from 'react';

import { useAppearance, useLabel } from '@supportx/ui';

import { nameOf } from '../admin/assets/shared';
import type { TypeNode } from '../admin/assets/tree';
import { ALL_TYPES, branchCounts, startsWith, TYPEAHEAD_MS } from './typeCounts';

interface Row {
  id: string;
  name: string;
  level: number;
  parent: string | null;
  setSize: number;
  position: number;
  children: string[];
  count: number;
}

/**
 * The product type tree beside the asset list (WP-049b s4a; REQ-AST-047 AC1, AC2).
 *
 * Its own WAI-ARIA tree, not Ant Design's Tree: that one keeps focus on a hidden input and has no
 * Home/End, which the spec asks for (SDP's tree "responds only to real mouse clicks"). One row
 * takes the focus at a time (roving tabindex); Up/Down move, Right opens a branch or goes to its
 * first child, Left closes it or goes to the parent (mirrored in right to left), Home/End jump
 * to the first or last row, Enter or Space choose. It is a plain list, so it scrolls normally.
 */
export function TypeTree({
  nodes,
  counts,
  total,
  selected,
  onSelect,
}: {
  nodes: TypeNode[];
  /** Live assets per type, that type only. */
  counts: ReadonlyMap<string, number>;
  /** All the view's assets. */
  total: number | undefined;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const t = useLabel();
  const { locale, direction } = useAppearance();
  const { token } = theme.useToken();
  // Branches start open (the types load after the first render): what was closed is kept.
  const [closed, setClosed] = useState<ReadonlySet<string>>(() => new Set());
  const [focused, setFocused] = useState<string>(selected);
  const refs = useRef(new Map<string, HTMLLIElement>());
  const branch = useMemo(() => branchCounts(nodes, counts), [nodes, counts]);
  const rows = useMemo(() => {
    const found = new Map<string, Row>();
    // "Every type" first, beside the top types (one level): choosing it clears the filter.
    found.set(ALL_TYPES, {
      id: ALL_TYPES,
      name: t('assets.tree.all_types'),
      level: 1,
      parent: null,
      setSize: nodes.length + 1,
      position: 1,
      children: [],
      count: total ?? 0,
    });
    const add = (list: TypeNode[], level: number, parent: string | null) => {
      const shift = parent === null ? 1 : 0;
      list.forEach((node, index) => {
        found.set(node.id, {
          id: node.id,
          name: nameOf(node.names, locale),
          level,
          parent,
          setSize: list.length + shift,
          position: index + 1 + shift,
          children: (node.children ?? []).map((c) => c.id),
          count: branch.get(node.id) ?? 0,
        });
        add(node.children ?? [], level + 1, node.id);
      });
    };
    add(nodes, 1, null);
    return found;
  }, [nodes, branch, total, locale, t]);
  const isOpen = (id: string) => !closed.has(id);
  // The rows a person can reach now, in order (closed branches hide their rows).
  const visible: string[] = [];
  const collect = (id: string) => {
    visible.push(id);
    const row = rows.get(id);
    if (row !== undefined && isOpen(id)) row.children.forEach(collect);
  };
  visible.push(ALL_TYPES);
  nodes.forEach((n) => {
    collect(n.id);
  });
  const current = visible.includes(focused) ? focused : (visible[0] ?? ALL_TYPES);
  const focus = (id: string | undefined) => {
    if (id === undefined) return;
    setFocused(id);
    refs.current.get(id)?.focus();
  };
  const toggle = (id: string, to: boolean) => {
    setClosed((before) => {
      const next = new Set(before);
      if (to) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  // Typeahead (WAI-ARIA tree pattern): a printable key moves to the next visible row whose name
  // starts with it, wrapping; keys typed within TYPEAHEAD_MS form a prefix.
  const typed = useRef({ text: '', at: 0 });
  const typeahead = (event: KeyboardEvent<HTMLLIElement>, id: string): boolean => {
    if (
      event.key.length !== 1 ||
      event.key === ' ' ||
      event.ctrlKey ||
      event.metaKey ||
      event.altKey
    ) {
      return false;
    }
    const now = event.timeStamp;
    const text =
      now - typed.current.at <= TYPEAHEAD_MS ? typed.current.text + event.key : event.key;
    typed.current = { text, at: now };
    const at = visible.indexOf(id);
    // A longer prefix may still match the current row; a fresh key looks from the next one.
    const start = text.length > 1 ? at : at + 1;
    const order = [...visible.slice(start), ...visible.slice(0, start)];
    const found = order.find((key) => startsWith(rows.get(key)?.name ?? '', text, locale));
    if (found !== undefined) focus(found);
    return true;
  };
  const onKeyDown = (event: KeyboardEvent<HTMLLIElement>, id: string) => {
    const row = rows.get(id);
    if (row === undefined) return;
    const at = visible.indexOf(id);
    const rtl = direction === 'rtl';
    const forward = rtl ? 'ArrowLeft' : 'ArrowRight';
    const back = rtl ? 'ArrowRight' : 'ArrowLeft';
    switch (event.key) {
      case 'ArrowDown':
        focus(visible[at + 1]);
        break;
      case 'ArrowUp':
        focus(visible[at - 1]);
        break;
      case 'Home':
        focus(visible[0]);
        break;
      case 'End':
        focus(visible.at(-1));
        break;
      case forward:
        if (row.children.length === 0) break;
        if (isOpen(id)) focus(row.children[0]);
        else toggle(id, true);
        break;
      case back:
        if (row.children.length > 0 && isOpen(id)) toggle(id, false);
        else if (row.parent !== null) focus(row.parent);
        break;
      case 'Enter':
      case ' ':
        onSelect(id);
        break;
      default:
        if (!typeahead(event, id)) return;
    }
    event.preventDefault();
    event.stopPropagation();
  };
  const render = (id: string) => {
    const row = rows.get(id);
    if (row === undefined) return null;
    const expandable = row.children.length > 0;
    const chosen = id === selected;
    const Caret = isOpen(id)
      ? CaretDownOutlined
      : direction === 'rtl'
        ? CaretLeftOutlined
        : CaretRightOutlined;
    return (
      <li
        key={id}
        ref={(element) => {
          if (element === null) refs.current.delete(id);
          else refs.current.set(id, element);
        }}
        role="treeitem"
        aria-level={row.level}
        aria-setsize={row.setSize}
        aria-posinset={row.position}
        aria-selected={chosen}
        aria-expanded={expandable ? isOpen(id) : undefined}
        tabIndex={id === current ? 0 : -1}
        onKeyDown={(event) => {
          onKeyDown(event, id);
        }}
        onFocus={(event) => {
          if (event.target === event.currentTarget) setFocused(id);
        }}
        data-testid={`asset-tree-${id === ALL_TYPES ? 'all' : id}`}
        className="sx-type-tree-item"
        style={{ listStyle: 'none', outline: 'none' }}
      >
        <div
          className="sx-type-tree-row"
          onClick={() => {
            setFocused(id);
            onSelect(id);
          }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            paddingBlock: 4,
            paddingInlineStart: (row.level - 1) * 16 + 4,
            paddingInlineEnd: 8,
            cursor: 'pointer',
            borderRadius: token.borderRadiusSM,
            background: chosen ? token.controlItemBgActive : undefined,
            fontWeight: chosen ? 600 : undefined,
          }}
        >
          <span
            aria-hidden
            onClick={(event) => {
              if (!expandable) return;
              event.stopPropagation();
              toggle(id, !isOpen(id));
            }}
            style={{ width: 14, display: 'inline-flex', color: token.colorTextSecondary }}
          >
            {expandable && <Caret style={{ fontSize: 10 }} />}
          </span>
          <bdi dir="auto" style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>
            {row.name}
          </bdi>
          <Typography.Text type="secondary" data-testid={`asset-tree-count-${id || 'all'}`}>
            {/* Read with the name: "Laptop, 12 assets". */}
            <span className="sr-only">{', '}</span>
            {t('assets.tree.count', { count: row.count })}
          </Typography.Text>
        </div>
        {expandable && isOpen(id) && (
          <ul role="group" style={{ margin: 0, padding: 0 }}>
            {row.children.map(render)}
          </ul>
        )}
      </li>
    );
  };
  return (
    <>
      {/* Focus shows on the row (not the whole branch), in the theme's own focus colour and
          width, so it is visible in light, dark and high contrast alike. */}
      <style>
        {`.sx-type-tree-item:focus-visible > .sx-type-tree-row { outline: ${String(
          token.lineWidthFocus,
        )}px solid ${token.colorPrimary}; outline-offset: -${String(token.lineWidthFocus)}px; }`}
      </style>
      <ul
        role="tree"
        aria-label={t('assets.tree.label')}
        style={{ margin: 0, padding: 0 }}
        data-testid="asset-tree"
      >
        {render(ALL_TYPES)}
        {nodes.map((n) => render(n.id))}
      </ul>
    </>
  );
}
