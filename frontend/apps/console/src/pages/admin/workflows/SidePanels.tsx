import { DeleteOutlined } from '@ant-design/icons';
import { Alert, Button, Collapse, Descriptions, Flex, Form, Input, Select, Typography } from 'antd';
import { useState } from 'react';

import type { WorkflowEdge, WorkflowNode, WorkflowVariable } from '@supportx/flow';
import { EmptyText, useLabel } from '@supportx/ui';

import { NodeForm } from './NodeForms';
import { FORM_TYPES, portName, problemText } from './nodes';

export interface NodeProblem {
  code: string;
  params: Record<string, unknown>;
}

/**
 * The selected node's details (REQ-WF-008): its type and id, its settings and the problems
 * the last save found on it. A type people use most has its own form (NodeForms); every type
 * keeps "Advanced", its settings as the definition stores them. The form and the advanced
 * text are one draft; nothing applies until "Apply" (one undo step), and text that is not
 * JSON never applies.
 */

/** A step's name in words, numbered when its type repeats; never its internal id (QA F-07). */
function nodeName(
  t: (key: string, params?: Record<string, string | number>) => string,
  node: WorkflowNode,
): string {
  const type = t(`workflow_node_type.${node.data.nodeType}`);
  return node.data.n === undefined ? type : t('workflows.step_numbered', { type, n: node.data.n });
}

export function NodeDetails({
  node,
  recordType,
  variables,
  problems,
  readOnly,
  onConfig,
  onDelete,
}: {
  node: WorkflowNode;
  recordType: string;
  variables: WorkflowVariable[];
  problems: NodeProblem[];
  readOnly: boolean;
  onConfig: (config: Record<string, unknown>) => void;
  onDelete: () => void;
}) {
  const t = useLabel();
  const [draft, setDraft] = useState<Record<string, unknown>>(node.data.config);
  const [text, setText] = useState(() => JSON.stringify(node.data.config, null, 2));
  const [bad, setBad] = useState(false);
  const hasForm = FORM_TYPES.has(node.data.nodeType);
  const fromForm = (next: Record<string, unknown>) => {
    setDraft(next);
    setText(JSON.stringify(next, null, 2));
    setBad(false);
  };
  const apply = () => {
    try {
      const parsed: unknown = JSON.parse(text);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setBad(true);
        return;
      }
      setBad(false);
      setDraft(parsed as Record<string, unknown>);
      onConfig(parsed as Record<string, unknown>);
    } catch {
      setBad(true);
    }
  };
  const changed = text !== JSON.stringify(node.data.config, null, 2);
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
        <>
          {hasForm && (
            <NodeForm
              type={node.data.nodeType}
              config={draft}
              onChange={fromForm}
              recordType={recordType}
              variables={variables}
              readOnly={readOnly}
            />
          )}
          <Collapse
            size="small"
            defaultActiveKey={hasForm ? [] : ['advanced']}
            items={[
              {
                key: 'advanced',
                label: t('workflows.designer.advanced'),
                children: (
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
                  </Form>
                ),
              },
            ]}
          />
          {!readOnly && (
            <Button
              type="primary"
              disabled={!changed}
              onClick={apply}
              data-testid="designer-node-apply"
            >
              {t('workflows.designer.apply')}
            </Button>
          )}
        </>
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
            {nodeName(t, n)}
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
                            label: nodeName(t, target),
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
