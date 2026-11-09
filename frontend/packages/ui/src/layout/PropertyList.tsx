import { EditOutlined, PlusOutlined, UpOutlined } from '@ant-design/icons';
import { Button, Typography, theme } from 'antd';
import { useState, type MouseEvent, type ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE, TYPE } from '../density';

import { PropertyRow } from './RecordPage';

export interface PropertyItem {
  key: string;
  label: ReactNode;
  /** The value, or its in-place editor. */
  content: ReactNode;
  /** Holds a value: shown at once. Empty ones wait behind "Add details". */
  filled: boolean;
  /** Shown even when empty (a field everybody looks for). */
  always?: boolean;
  testId?: string;
}

/**
 * Template A's properties (D-147): only the fields that hold a value, then "Add details" for the
 * empty ones, so the panel reads as facts rather than a form full of dashes. Values edit in
 * place (EditableValue); no pencil on every row.
 */
export function PropertyList({ items, testId }: { items: PropertyItem[]; testId?: string }) {
  const t = useLabel();
  const [showEmpty, setShowEmpty] = useState(false);
  const shown = items.filter((i) => i.filled || i.always === true);
  const empty = items.filter((i) => !i.filled && i.always !== true);
  const row = (i: PropertyItem) => (
    <PropertyRow key={i.key} label={i.label} testId={i.testId}>
      {i.content}
    </PropertyRow>
  );
  return (
    <div data-testid={testId}>
      {shown.map(row)}
      {showEmpty && (
        <div data-testid={testId === undefined ? undefined : `${testId}-empty`}>
          {empty.map(row)}
        </div>
      )}
      {empty.length > 0 && (
        <Button
          type="link"
          size="small"
          icon={showEmpty ? <UpOutlined aria-hidden /> : <PlusOutlined aria-hidden />}
          aria-expanded={showEmpty}
          style={{ paddingInline: 0, marginTop: SPACE.xxs }}
          onClick={() => {
            setShowEmpty((v) => !v);
          }}
          data-testid={testId === undefined ? undefined : `${testId}-add`}
        >
          {showEmpty
            ? t('layout.properties_fewer')
            : t('layout.properties_add', { n: empty.length })}
        </Button>
      )}
    </div>
  );
}

/**
 * A value that edits on a click (template A): no pencil on every row, a hover background
 * instead. The value stays plain content, read as itself, with its links reachable (never inside
 * a role=button: lane A's #293 review, axe nested-interactive). Keyboard and screen-reader users
 * get a real "Edit <field>" button right after it, shown when it has focus. Empty values read
 * "Add".
 */
export function EditableValue({
  label,
  onEdit,
  empty = false,
  children,
  testId,
}: {
  /** The field's name, for the edit button's name ("Edit Urgency"). */
  label: string;
  onEdit: () => void;
  empty?: boolean;
  children: ReactNode;
  testId?: string;
}) {
  const t = useLabel();
  const { token } = theme.useToken();
  const [hover, setHover] = useState(false);
  const click = (event: MouseEvent<HTMLDivElement>) => {
    // A link or control inside the value does its own thing (a person, a linked record).
    const target = event.target as Element;
    if (target.closest('a, button, input, [role="button"]') !== null) return;
    onEdit();
  };
  return (
    <div
      onClick={click}
      onMouseEnter={() => {
        setHover(true);
      }}
      onMouseLeave={() => {
        setHover(false);
      }}
      style={{
        cursor: 'pointer',
        borderRadius: token.borderRadiusSM,
        marginInline: -SPACE.xxs,
        paddingInline: SPACE.xxs,
        minHeight: 22,
        background: hover ? token.colorFillTertiary : undefined,
        boxShadow: hover ? `0 0 0 1px ${token.colorBorder}` : undefined,
      }}
    >
      {empty ? (
        <Typography.Text type="secondary" style={{ fontSize: TYPE.data }}>
          {t('layout.add_value')}
        </Typography.Text>
      ) : (
        children
      )}
      <button
        type="button"
        className="sx-edit-trigger"
        aria-label={t('layout.edit_field', { field: label })}
        onClick={(event) => {
          event.stopPropagation();
          onEdit();
        }}
        data-testid={testId}
      >
        <EditOutlined aria-hidden />
      </button>
    </div>
  );
}
