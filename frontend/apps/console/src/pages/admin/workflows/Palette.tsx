import { Button, Flex, Tooltip, Typography } from 'antd';

import type { NodeTypeOut } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

import { CATEGORIES, problemText } from './nodes';

export const DRAG_TYPE = 'application/x-supportx-node';

/**
 * The node palette (REQ-WF-008, REQ-WF-028): each type by name in its named group. A type is
 * added by dragging it onto the canvas, or by its button (Enter or click), which places it
 * below the selected node: the keyboard path never needs a drag. A type the record type has
 * but cannot use now is shown disabled with the reason.
 */
export function Palette({
  types,
  onAdd,
  readOnly,
}: {
  types: NodeTypeOut[];
  onAdd: (type: string) => void;
  readOnly: boolean;
}) {
  const t = useLabel();
  return (
    <Flex
      vertical
      gap={12}
      role="group"
      aria-label={t('workflows.designer.palette')}
      data-testid="designer-palette"
    >
      {CATEGORIES.map((category) => {
        const members = types.filter((n) => n.category === category && n.type !== 'start');
        if (members.length === 0) return null;
        return (
          <Flex key={category} vertical gap={4}>
            <Typography.Text type="secondary" strong style={{ fontSize: 12 }}>
              {t(`workflow_node_category.${category}`)}
            </Typography.Text>
            {members.map((n) => {
              const why = n.why_not === null ? undefined : problemText(t, n.why_not);
              const disabled = readOnly || !n.available;
              const button = (
                <Button
                  block
                  size="small"
                  disabled={disabled}
                  draggable={!disabled}
                  onDragStart={(e) => {
                    e.dataTransfer.setData(DRAG_TYPE, n.type);
                    e.dataTransfer.effectAllowed = 'move';
                  }}
                  onClick={() => {
                    onAdd(n.type);
                  }}
                  style={{ justifyContent: 'flex-start' }}
                  aria-label={t('workflows.designer.add_node', {
                    type: t(`workflow_node_type.${n.type}`),
                  })}
                  data-testid={`palette-${n.type}`}
                >
                  {t(`workflow_node_type.${n.type}`)}
                </Button>
              );
              return why === undefined ? (
                <span key={n.type}>{button}</span>
              ) : (
                <Tooltip key={n.type} title={why}>
                  <span>{button}</span>
                </Tooltip>
              );
            })}
          </Flex>
        );
      })}
    </Flex>
  );
}
