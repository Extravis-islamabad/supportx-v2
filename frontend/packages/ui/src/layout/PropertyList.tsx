import { PlusOutlined, UpOutlined } from '@ant-design/icons';
import { Button, Typography, theme } from 'antd';
import { useState, type KeyboardEvent, type ReactNode } from 'react';

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
 * A value that edits on a click (template A): the whole value is the control, with a hover
 * background instead of a pencil. Keyboard: Enter or Space. Empty values read "Add".
 */
export function EditableValue({
  label,
  onEdit,
  empty = false,
  children,
  testId,
}: {
  /** The field's name, for the accessible name ("Edit Urgency"). */
  label: string;
  onEdit: () => void;
  empty?: boolean;
  children: ReactNode;
  testId?: string;
}) {
  const t = useLabel();
  const { token } = theme.useToken();
  const [hover, setHover] = useState(false);
  const key = (event: KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onEdit();
    }
  };
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={t('layout.edit_field', { field: label })}
      onClick={onEdit}
      onKeyDown={key}
      onMouseEnter={() => {
        setHover(true);
      }}
      onMouseLeave={() => {
        setHover(false);
      }}
      onFocus={() => {
        setHover(true);
      }}
      onBlur={() => {
        setHover(false);
      }}
      data-testid={testId}
      style={{
        cursor: 'pointer',
        borderRadius: token.borderRadiusSM,
        marginInline: -SPACE.xxs,
        paddingInline: SPACE.xxs,
        minHeight: 22,
        background: hover ? token.colorFillTertiary : undefined,
        outline: 'none',
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
    </div>
  );
}
