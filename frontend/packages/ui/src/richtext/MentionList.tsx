import type { SuggestionKeyDownProps, SuggestionProps } from '@tiptap/suggestion';
import { Flex, Tag, Typography, theme } from 'antd';
import { forwardRef, useImperativeHandle, useState } from 'react';

import { useLabel } from '../appearance';
import type { MentionCandidate } from './mention';

export interface ListHandle {
  onKeyDown: (props: SuggestionKeyDownProps) => boolean;
}

export type ListProps = SuggestionProps<MentionCandidate, { id: string; label: string }>;

export const MentionList = forwardRef<ListHandle, ListProps>(function MentionList(props, ref) {
  const t = useLabel();
  const { token } = theme.useToken();
  const [active, setActive] = useState(0);
  const [items, setItems] = useState(props.items);
  if (items !== props.items) {
    setItems(props.items);
    setActive(0);
  }
  const pick = (index: number) => {
    const item = props.items[index];
    if (item !== undefined) props.command({ id: item.id, label: item.label });
  };
  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (props.items.length === 0) return false;
      if (event.key === 'ArrowDown') {
        setActive((index) => (index + 1) % props.items.length);
        return true;
      }
      if (event.key === 'ArrowUp') {
        setActive((index) => (index + props.items.length - 1) % props.items.length);
        return true;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        pick(active);
        return true;
      }
      return false;
    },
  }));
  return (
    <div
      role="listbox"
      aria-label={t('richtext.mention_list')}
      data-testid="rt-mention-list"
      style={{
        // Mounted on document.body, outside the themed tree: set text colour and font here.
        background: token.colorBgElevated,
        color: token.colorText,
        fontFamily: token.fontFamily,
        fontSize: token.fontSize,
        boxShadow: token.boxShadowSecondary,
        borderRadius: token.borderRadiusLG,
        padding: 4,
        minWidth: 240,
        maxWidth: 360,
      }}
    >
      {props.items.length === 0 ? (
        <Typography.Text type="secondary" style={{ padding: 8, display: 'block' }}>
          {t('richtext.mention_none')}
        </Typography.Text>
      ) : (
        props.items.map((item, index) => (
          <div
            key={item.id}
            role="option"
            aria-selected={index === active}
            data-testid="rt-mention-option"
            onMouseDown={(event) => {
              event.preventDefault();
              pick(index);
            }}
            onMouseEnter={() => {
              setActive(index);
            }}
            style={{
              padding: '4px 8px',
              borderRadius: token.borderRadius,
              cursor: 'pointer',
              background: index === active ? token.controlItemBgActive : undefined,
            }}
          >
            <Flex justify="space-between" align="center" gap={8}>
              <Flex vertical style={{ minWidth: 0 }}>
                <bdi dir="auto">{item.label}</bdi>
                <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                  {item.email}
                </Typography.Text>
              </Flex>
              {!item.canSee && (
                <Tag color="warning" style={{ marginInlineEnd: 0 }}>
                  {t('richtext.mention_cannot_see')}
                </Tag>
              )}
            </Flex>
          </div>
        ))
      )}
    </div>
  );
});
