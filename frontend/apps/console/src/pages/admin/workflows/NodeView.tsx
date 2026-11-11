import { Flex, Typography, theme } from 'antd';
import { memo } from 'react';

import { Handle, INPUT, Position, type NodeProps, type WorkflowNode } from '@supportx/flow';
import { useLabel } from '@supportx/ui';

import { CATEGORY_OF, portName } from './nodes';

/**
 * One node on the canvas (REQ-WF-028): its name in words, its id, and its handles always
 * visible. Each output is its own labelled handle at the bottom, so a link always says which
 * way it leaves ("Approved", "Timed out"); the input sits at the top. A node with a problem
 * has a red border and says so in words for screen readers.
 */
export const NodeView = memo(function NodeView({ id, data, selected }: NodeProps<WorkflowNode>) {
  const t = useLabel();
  const { token } = theme.useToken();
  const flagged = data.problems !== undefined && data.problems > 0;
  const current = data.state === 'current';
  const passed = data.state === 'passed';
  const border = flagged
    ? token.colorError
    : current
      ? token.colorPrimary
      : selected
        ? token.colorPrimaryBorder
        : token.colorBorder;
  const category = CATEGORY_OF[data.nodeType];
  return (
    <div
      data-testid={`node-${id}`}
      data-state={data.state}
      style={{
        minWidth: 180,
        maxWidth: 240,
        background: passed ? token.colorSuccessBg : token.colorBgContainer,
        border: `${String(current || selected || flagged ? 2 : 1)}px solid ${border}`,
        borderRadius: token.borderRadiusLG,
        padding: '8px 12px 20px',
        boxShadow: selected ? token.boxShadowSecondary : undefined,
      }}
    >
      {/* Handles are for the pointer; keyboard and screen readers link through the outline
          (REQ-WF-028), so they carry no label of their own (axe: aria-prohibited-attr). */}
      {data.nodeType !== 'start' && (
        <Handle
          type="target"
          id={INPUT}
          position={Position.Top}
          // Always visible, large enough to hit (REQ-WF-028: no hover-only dots).
          style={{ width: 12, height: 12, background: token.colorTextSecondary }}
        />
      )}
      <Flex vertical gap={2}>
        {category !== undefined && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t(`workflow_node_category.${category}`)}
          </Typography.Text>
        )}
        <Typography.Text strong>{t(`workflow_node_type.${data.nodeType}`)}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }} dir="ltr">
          {id}
        </Typography.Text>
        {flagged && (
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            {t('workflows.designer.node_problems', { count: data.problems ?? 0 })}
          </Typography.Text>
        )}
      </Flex>
      {data.ports.map((port, i) => (
        <Handle
          key={port}
          type="source"
          id={port}
          position={Position.Bottom}
          style={{
            left: `${String(((i + 1) / (data.ports.length + 1)) * 100)}%`,
            width: 12,
            height: 12,
            background: token.colorPrimary,
          }}
        >
          <span
            style={{
              position: 'absolute',
              top: 12,
              insetInlineStart: '50%',
              transform: 'translateX(-50%)',
              fontSize: 11,
              whiteSpace: 'nowrap',
              color: token.colorTextSecondary,
              pointerEvents: 'none',
            }}
          >
            {data.ports.length > 1 ? portName(t, data.nodeType, port) : ''}
          </span>
        </Handle>
      ))}
    </div>
  );
});
