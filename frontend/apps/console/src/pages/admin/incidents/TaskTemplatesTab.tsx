import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Drawer,
  Flex,
  Form,
  Input,
  InputNumber,
  List,
  Select,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useAllTaskTemplates,
  useTaskTemplateChange,
  type TaskPriority,
  type TaskTemplate,
} from '@supportx/api-client';
import { EmptyText, lengthLimit, reportError, useLabel, WriteButton } from '@supportx/ui';

const PRIORITIES: readonly TaskPriority[] = ['low', 'normal', 'high'];
const MAX_TASKS = 20;

interface Row {
  title: string;
  priority: TaskPriority;
  estimated_minutes: number | null;
}
interface Draft {
  name: string;
  description: string;
  tasks: Row[];
  disabled: boolean;
}
type Editing = { kind: 'create' } | { kind: 'update'; template: TaskTemplate } | null;

function draftOf(template: TaskTemplate | undefined): Draft {
  return {
    name: template?.name ?? '',
    description: template?.description ?? '',
    tasks: template?.tasks.map((x) => ({
      title: x.title,
      priority: x.priority,
      estimated_minutes: x.estimated_minutes ?? null,
    })) ?? [{ title: '', priority: 'normal', estimated_minutes: null }],
    disabled: template?.disabled ?? false,
  };
}

/**
 * Task templates (WP-046a S1; REQ-INC-074): one task or a set of up to 20 that technicians add
 * to a record, each ready to edit. A disabled template stays listed here and is no longer
 * offered on records (AC2). Kept by those who configure the service desk.
 */
export function TaskTemplatesTab() {
  const t = useLabel();
  const templates = useAllTaskTemplates();
  const change = useTaskTemplateChange();
  const [editing, setEditing] = useState<Editing>(null);
  const [draft, setDraft] = useState<Draft>(draftOf(undefined));
  const [problems, setProblems] = useState<string[]>([]);
  const start = (next: Editing) => {
    setProblems([]);
    setEditing(next);
    setDraft(draftOf(next?.kind === 'update' ? next.template : undefined));
  };
  const setRow = (index: number, row: Partial<Row>) => {
    setDraft((d) => ({
      ...d,
      tasks: d.tasks.map((r, i) => (i === index ? { ...r, ...row } : r)),
    }));
  };
  const ready = draft.name.trim() !== '' && draft.tasks.every((r) => r.title.trim() !== '');
  const save = () => {
    if (editing === null) return;
    const body = {
      name: draft.name.trim(),
      description: draft.description.trim() === '' ? null : draft.description.trim(),
      tasks: draft.tasks.map((r) => ({
        title: r.title.trim(),
        priority: r.priority,
        estimated_minutes: r.estimated_minutes,
      })),
    };
    change.mutate(
      editing.kind === 'create'
        ? { kind: 'create', template: body }
        : {
            kind: 'update',
            templateId: editing.template.id,
            version: editing.template.version,
            template: { ...body, disabled: draft.disabled },
          },
      {
        onSuccess: () => {
          setEditing(null);
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422) {
            setProblems(error.fieldErrors.map((f) => t(f.message_key, f.params ?? {})));
            return;
          }
          reportError(error);
        },
      },
    );
  };
  const rows = templates.data ?? [];
  return (
    <Card
      title={t('settings.task_templates.title')}
      extra={
        <WriteButton
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            start({ kind: 'create' });
          }}
          data-testid="task-templates-add"
        >
          {t('settings.task_templates.add')}
        </WriteButton>
      }
      data-testid="task-templates"
    >
      <Typography.Paragraph type="secondary">
        {t('settings.task_templates.help')}
      </Typography.Paragraph>
      <List
        loading={templates.isLoading}
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('settings.task_templates.none')}</EmptyText> }}
        renderItem={(template) => (
          <List.Item
            key={template.id}
            actions={[
              <Button
                key="edit"
                type="link"
                onClick={() => {
                  start({ kind: 'update', template });
                }}
                data-testid={`task-template-edit-${template.id}`}
              >
                {t('actions.edit')}
              </Button>,
            ]}
          >
            <Flex gap={8} wrap align="center">
              <bdi>{template.name}</bdi>
              <Typography.Text type="secondary">
                {t('settings.task_templates.task_count', { count: template.tasks.length })}
              </Typography.Text>
              {template.disabled && <Tag>{t('settings.task_templates.disabled')}</Tag>}
            </Flex>
          </List.Item>
        )}
      />
      {editing !== null && (
        <Drawer
          open
          width={600}
          title={t(
            editing.kind === 'create'
              ? 'settings.task_templates.add'
              : 'settings.task_templates.edit',
          )}
          onClose={() => {
            setEditing(null);
          }}
          destroyOnHidden
          extra={
            <Flex gap={8}>
              <Button
                onClick={() => {
                  setEditing(null);
                }}
              >
                {t('actions.cancel')}
              </Button>
              <Button
                type="primary"
                disabled={!ready}
                loading={change.isPending}
                onClick={save}
                data-testid="task-template-save"
              >
                {t('actions.save')}
              </Button>
            </Flex>
          }
        >
          <Form layout="vertical">
            {problems.length > 0 && (
              <Typography.Text type="danger" role="alert">
                {problems.join(' ')}
              </Typography.Text>
            )}
            <Form.Item label={t('settings.task_templates.name')} htmlFor="task-template-name">
              <Input
                id="task-template-name"
                value={draft.name}
                count={lengthLimit(200)}
                onChange={(e) => {
                  setDraft({ ...draft, name: e.target.value });
                }}
                data-testid="task-template-name"
              />
            </Form.Item>
            <Form.Item
              label={t('settings.task_templates.description')}
              htmlFor="task-template-description"
            >
              <Input.TextArea
                id="task-template-description"
                value={draft.description}
                count={lengthLimit(2000)}
                autoSize={{ minRows: 2 }}
                onChange={(e) => {
                  setDraft({ ...draft, description: e.target.value });
                }}
              />
            </Form.Item>
            <Typography.Text strong>{t('settings.task_templates.tasks')}</Typography.Text>
            {draft.tasks.map((row, index) => (
              <Flex key={index} gap={8} wrap align="center" style={{ marginBlock: 8 }}>
                <Input
                  aria-label={t('settings.task_templates.task_title', { n: index + 1 })}
                  value={row.title}
                  count={lengthLimit(200)}
                  onChange={(e) => {
                    setRow(index, { title: e.target.value });
                  }}
                  style={{ flex: '1 1 220px' }}
                  data-testid={`task-template-task-${String(index)}`}
                />
                <Select<TaskPriority>
                  aria-label={t('settings.task_templates.task_priority', { n: index + 1 })}
                  value={row.priority}
                  onChange={(priority) => {
                    setRow(index, { priority });
                  }}
                  options={PRIORITIES.map((p) => ({ value: p, label: t(`task_priority.${p}`) }))}
                  style={{ minWidth: 110 }}
                />
                <InputNumber
                  aria-label={t('settings.task_templates.task_estimate', { n: index + 1 })}
                  placeholder={t('task.field.estimated_minutes')}
                  min={0}
                  max={525600}
                  value={row.estimated_minutes}
                  onChange={(v) => {
                    setRow(index, { estimated_minutes: v });
                  }}
                />
                <Button
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  disabled={draft.tasks.length === 1}
                  aria-label={t('settings.task_templates.remove_task', { n: index + 1 })}
                  onClick={() => {
                    setDraft({ ...draft, tasks: draft.tasks.filter((_, i) => i !== index) });
                  }}
                />
              </Flex>
            ))}
            <Button
              icon={<PlusOutlined />}
              disabled={draft.tasks.length >= MAX_TASKS}
              onClick={() => {
                setDraft({
                  ...draft,
                  tasks: [
                    ...draft.tasks,
                    { title: '', priority: 'normal', estimated_minutes: null },
                  ],
                });
              }}
              data-testid="task-template-add-task"
            >
              {t('settings.task_templates.add_task')}
            </Button>
            {editing.kind === 'update' && (
              <Flex gap={12} align="start" style={{ marginTop: 16 }}>
                <Switch
                  id="task-template-disabled"
                  checked={draft.disabled}
                  onChange={(disabled) => {
                    setDraft({ ...draft, disabled });
                  }}
                />
                <label htmlFor="task-template-disabled">
                  <Typography.Text strong>{t('settings.task_templates.disable')}</Typography.Text>
                  <br />
                  <Typography.Text type="secondary">
                    {t('settings.task_templates.disable_help')}
                  </Typography.Text>
                </label>
              </Flex>
            )}
          </Form>
        </Drawer>
      )}
    </Card>
  );
}
