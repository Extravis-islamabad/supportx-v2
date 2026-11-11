import { DeleteOutlined } from '@ant-design/icons';
import { Alert, Button, Descriptions, Flex, Form, Input, Select, Typography } from 'antd';
import { useState } from 'react';

import type { WorkflowEdge, WorkflowNode } from '@supportx/flow';
import { EmptyText, useLabel } from '@supportx/ui';

import { portName, problemText } from './nodes';

export interface NodeProblem {
  code: string;
  params: Record<string, unknown>;
}

/**
 * The selected node's details (REQ-WF-008): its type and id, its settings and the problems
 * the last save found on it. Settings are edited as the definition stores them; a node with
 * its own form gets it in the next step of S4 (forms per node type), this editor stays for
 * the rest. Nothing applies until "Apply", and text that is not JSON never applies.
 */
export function NodeDetails({
  node,
  problems,
  readOnly,
  onConfig,
  onDelete,
}: {
  node: WorkflowNode;
  problems: NodeProblem[];
  readOnly: boolean;
  onConfig: (config: Record<string, unknown>) => void;
  onDelete: () => void;
}) {
  const t = useLabel();
  const [text, setText] = useState(() => JSON.stringify(node.data.config, null, 2));
  const [bad, setBad] = useState(false);
  const apply = () => {
    try {
      const parsed: unknown = JSON.parse(text);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setBad(true);
        return;
      }
      setBad(false);
      onConfig(parsed as Record<string, unknown>);
    } catch {
      setBad(true);
    }
  };
  return (
    <Flex vertical gap={12} data-testid="designer-node-details">
      <Descriptions
        size="small"
        column={1}
        items={[
          {
            key: 'type',
            label: t('workflows.designer.type'),
            children: t(`workflow_node_type.${node.data.nodeType}`),
          },
          {
            key: 'id',
            label: t('workflows.designer.node_id'),
            children: <bdi dir="ltr">{node.id}</bdi>,
          },
        ]}
      />
      {problems.length > 0 && (
        <Alert
          type="error"
          showIcon
          message={t('workflows.designer.node_problems', { count: problems.length })}
          description={
            <ul style={{ margin: 0, paddingInlineStart: 16 }}>
              {problems.map((p, i) => (
                <li key={`${p.code}-${String(i)}`}>{problemText(t, p.code, p.params)}</li>
              ))}
            </ul>
          }
          data-testid="designer-node-problems"
        />
      )}
      {node.data.nodeType !== 'start' && node.data.nodeType !== 'end' && (
        <Form layout="vertical">
          <Form.Item
            label={t('workflows.designer.settings')}
            htmlFor="node-config"
            validateStatus={bad ? 'error' : undefined}
            help={bad ? t('workflows.designer.settings_not_json') : undefined}
          >
            <Input.TextArea
              id="node-config"
              dir="ltr"
              rows={10}
              value={text}
              readOnly={readOnly}
              spellCheck={false}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
              onChange={(e) => {
                setText(e.target.value);
              }}
              data-testid="designer-node-config"
            />
          </Form.Item>
          {!readOnly && (
            <Button onClick={apply} data-testid="designer-node-apply">
              {t('workflows.designer.apply')}
            </Button>
          )}
        </Form>
      )}
      {!readOnly && node.data.nodeType !== 'start' && (
        <Button
          danger
          icon={<DeleteOutlined />}
          onClick={onDelete}
          data-testid="designer-node-delete"
        >
          {t('workflows.designer.delete_node')}
        </Button>
      )}
    </Flex>
  );
}

/** The selected link: where it goes, and a clear delete action (REQ-WF-028). */
export function LinkDetails({
  edge,
  typeOf,
  readOnly,
  onDelete,
}: {
  edge: WorkflowEdge;
  typeOf: (id: string) => string;
  readOnly: boolean;
  onDelete: () => void;
}) {
  const t = useLabel();
  const port = edge.data?.port ?? edge.sourceHandle ?? '';
  return (
    <Flex vertical gap={12} data-testid="designer-link-details">
      <Typography.Text>
        {t('workflows.designer.link_text', {
          from: edge.source,
          port: portName(t, typeOf(edge.source), port),
          to: edge.target,
        })}
      </Typography.Text>
      {!readOnly && (
        <Button
          danger
          icon={<DeleteOutlined />}
          onClick={onDelete}
          data-testid="designer-link-delete"
        >
          {t('workflows.designer.delete_link')}
        </Button>
      )}
    </Flex>
  );
}

/**
 * Every node and where each of its outputs leads (REQ-WF-028 AC1): the whole diagram as a
 * list, so it can be built and read by keyboard and screen reader. Choosing a target links an
 * output; choosing "Not linked" deletes the link.
 */
export function Outline({
  nodes,
  edges,
  readOnly,
  onLink,
  onSelect,
}: {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  readOnly: boolean;
  onLink: (from: string, port: string, to: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const t = useLabel();
  if (nodes.length === 0) return <EmptyText>{t('workflows.designer.empty')}</EmptyText>;
  const targets = nodes.filter((n) => n.data.nodeType !== 'start');
  return (
    <ol
      aria-label={t('workflows.designer.outline')}
      style={{ margin: 0, paddingInlineStart: 20 }}
      data-testid="designer-outline"
    >
      {nodes.map((n) => (
        <li key={n.id} style={{ marginBottom: 12 }} data-testid={`outline-${n.id}`}>
          <Button
            type="link"
            style={{ padding: 0, height: 'auto' }}
            onClick={() => {
              onSelect(n.id);
            }}
          >
            {t('workflows.designer.outline_node', {
              type: t(`workflow_node_type.${n.data.nodeType}`),
              id: n.id,
            })}
          </Button>
          {n.data.ports.length > 0 && (
            <Flex vertical gap={4} style={{ marginTop: 4 }}>
              {n.data.ports.map((port) => {
                const link = edges.find(
                  (e) => e.source === n.id && (e.data?.port ?? e.sourceHandle) === port,
                );
                const label = t('workflows.designer.output_goes', {
                  port: portName(t, n.data.nodeType, port),
                });
                return (
                  <Flex key={port} gap={8} align="center" wrap>
                    <label htmlFor={`outline-${n.id}-${port}`} style={{ minWidth: 96 }}>
                      {label}
                    </label>
                    <Select<string>
                      id={`outline-${n.id}-${port}`}
                      size="small"
                      style={{ minWidth: 160 }}
                      disabled={readOnly}
                      value={link?.target ?? ''}
                      onChange={(to) => {
                        onLink(n.id, port, to === '' ? null : to);
                      }}
                      options={[
                        { value: '', label: t('workflows.designer.not_linked') },
                        ...targets
                          .filter((target) => target.id !== n.id)
                          .map((target) => ({
                            value: target.id,
                            label: t('workflows.designer.outline_node', {
                              type: t(`workflow_node_type.${target.data.nodeType}`),
                              id: target.id,
                            }),
                          })),
                      ]}
                      data-testid={`outline-link-${n.id}-${port}`}
                    />
                  </Flex>
                );
              })}
            </Flex>
          )}
        </li>
      ))}
    </ol>
  );
}
