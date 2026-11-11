import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { App, Flex, Form, Input, Select, Table } from 'antd';
import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  useCopyWorkflow,
  useCreateWorkflow,
  useDeleteWorkflow,
  useExportWorkflow,
  useImportWorkflow,
  useWorkflows,
  type WorkflowOut,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  EditDialog,
  FilterBar,
  FormProblem,
  lengthLimit,
  ListPage,
  NoAccess,
  PageHeader,
  RowActions,
  ToneTag,
  WriteButton,
  loadedEmpty,
  reportError,
  useAccess,
  useFormProblem,
  useLabel,
  usePageCrumbs,
} from '@supportx/ui';

import { WorkflowsNav } from './RunsPage';
import { WORKFLOW_TYPES, type WorkflowType } from './types';

/** Enabled, disabled or never published: the state an admin needs at a glance. */
export function WorkflowState({ workflow }: { workflow: WorkflowOut }) {
  const t = useLabel();
  if (workflow.published_version === null) {
    return <ToneTag tone="default">{t('workflows.state.draft')}</ToneTag>;
  }
  return workflow.enabled ? (
    <ToneTag tone="success">{t('workflows.state.enabled')}</ToneTag>
  ) : (
    <ToneTag tone="warning">{t('workflows.state.disabled')}</ToneTag>
  );
}

function AddDialog({ recordType, onClose }: { recordType: WorkflowType; onClose: () => void }) {
  const t = useLabel();
  const navigate = useNavigate();
  const create = useCreateWorkflow();
  const problem = useFormProblem();
  const [key] = useState(() => crypto.randomUUID());
  const [name, setName] = useState('');
  const [type, setType] = useState<WorkflowType>(recordType);
  return (
    <EditDialog
      open
      title={t('workflows.add')}
      okText={t('workflows.add')}
      saving={create.isPending}
      okDisabled={name.trim() === ''}
      okWhyNot={name.trim() === '' ? t('workflows.why.name') : undefined}
      dirty={name !== ''}
      onCancel={onClose}
      onOk={() => {
        create.mutate(
          { key, recordType: type, name: name.trim() },
          {
            onSuccess: (made) => void navigate(`/admin/workflows/${made.id}`),
            onError: (e) => {
              problem.show(e);
            },
          },
        );
      }}
      testId="workflow-add"
    >
      <Form layout="vertical">
        <FormProblem problem={problem} />
        <Form.Item label={t('workflows.name')} htmlFor="workflow-name" required>
          <Input
            id="workflow-name"
            count={lengthLimit(120)}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
            data-testid="workflow-name"
          />
        </Form.Item>
        <Form.Item label={t('workflows.record_type')} htmlFor="workflow-type">
          <Select<WorkflowType>
            id="workflow-type"
            value={type}
            onChange={setType}
            options={WORKFLOW_TYPES.map((v) => ({ value: v, label: t(`work_item_type.${v}`) }))}
            data-testid="workflow-type"
          />
        </Form.Item>
      </Form>
    </EditDialog>
  );
}

function CopyDialog({ workflow, onClose }: { workflow: WorkflowOut; onClose: () => void }) {
  const t = useLabel();
  const copy = useCopyWorkflow();
  const problem = useFormProblem();
  const [key] = useState(() => crypto.randomUUID());
  const [name, setName] = useState(t('workflows.copy_name', { name: workflow.name }));
  return (
    <EditDialog
      open
      title={t('workflows.copy_title', { name: workflow.name })}
      okText={t('workflows.copy')}
      saving={copy.isPending}
      okDisabled={name.trim() === ''}
      okWhyNot={name.trim() === '' ? t('workflows.why.name') : undefined}
      onCancel={onClose}
      onOk={() => {
        copy.mutate(
          { id: workflow.id, key, name: name.trim() },
          {
            onSuccess: onClose,
            onError: (e) => {
              problem.show(e);
            },
          },
        );
      }}
      testId="workflow-copy"
    >
      <Form layout="vertical">
        <FormProblem problem={problem} />
        <Form.Item label={t('workflows.name')} htmlFor="workflow-copy-name" required>
          <Input
            id="workflow-copy-name"
            count={lengthLimit(120)}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
            data-testid="workflow-copy-name"
          />
        </Form.Item>
      </Form>
    </EditDialog>
  );
}

/** Save a workflow's file, named after it (REQ-WF-027 AC2). */
function saveFile(name: string, content: unknown) {
  const blob = new Blob([JSON.stringify(content, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name.replace(/[^\p{L}\p{N}_-]+/gu, '-')}.workflow.json`;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Admin › Workflows (WP-048b S4; template C): a record type's workflows with their state,
 * published version and live runs; add, open, copy, export, import and delete (REQ-WF-027).
 * Live: another admin's change refetches the list (the workflows channel).
 */
export function WorkflowsPage() {
  const t = useLabel();
  const { can } = useAccess();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [recordType, setRecordType] = useState<WorkflowType>('incident');
  const [search, setSearch] = useState('');
  const [dialog, setDialog] = useState<'add' | WorkflowOut>();
  const allowed = can('workflows.manage');
  const list = useWorkflows(recordType, allowed);
  const remove = useDeleteWorkflow();
  const exporting = useExportWorkflow();
  const importing = useImportWorkflow();
  const fileInput = useRef<HTMLInputElement>(null);
  usePageCrumbs([{ label: t('nav.admin_workflows') }]);
  useListChannel(allowed ? 'workflows' : null, (m) => {
    if (m.type === 'workflows.changed' || m.type === 'workflow_instances.changed') {
      void queryClient.invalidateQueries({ queryKey: ['workflows', 'list'] });
    }
  });
  if (!allowed) return <NoAccess titleKey="nav.admin_workflows" />;
  const text = search.trim().toLocaleLowerCase();
  const rows = (list.data ?? []).filter(
    (w) => text === '' || w.name.toLocaleLowerCase().includes(text),
  );
  const onFile = (file: File) => {
    void file
      .text()
      .then((raw) => JSON.parse(raw) as Record<string, unknown>)
      .then((parsed) =>
        importing.mutateAsync({ key: crypto.randomUUID(), file: parsed }).then(() => {
          void message.success(t('workflows.imported'));
        }),
      )
      .catch((error: unknown) => {
        // A file that is not JSON never reaches the server; the server names the rest.
        if (error instanceof SyntaxError) void message.error(t('workflows.import_not_json'));
        else reportError(error);
      });
  };
  return (
    <ListPage
      testId="workflows-list"
      header={
        <Flex vertical gap={8}>
          <PageHeader
            title={t('nav.admin_workflows')}
            count={list.data === undefined ? undefined : String(rows.length)}
            testId="workflows-header"
            extra={
              <>
                <WriteButton
                  icon={<UploadOutlined />}
                  loading={importing.isPending}
                  onClick={() => fileInput.current?.click()}
                  data-testid="workflows-import"
                >
                  {t('workflows.import')}
                </WriteButton>
                <WriteButton
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => {
                    setDialog('add');
                  }}
                  data-testid="workflows-add"
                >
                  {t('workflows.add')}
                </WriteButton>
                <input
                  ref={fileInput}
                  type="file"
                  accept="application/json,.json"
                  hidden
                  aria-hidden
                  tabIndex={-1}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = '';
                    if (file !== undefined) onFile(file);
                  }}
                  data-testid="workflows-import-file"
                />
              </>
            }
          />
          <WorkflowsNav active="list" />
        </Flex>
      }
      filters={
        <FilterBar
          testId="workflows-filters"
          view={
            <Select<WorkflowType>
              style={{ minWidth: 200 }}
              prefix={`${t('workflows.record_type')}:`}
              aria-label={t('workflows.record_type')}
              value={recordType}
              onChange={setRecordType}
              options={WORKFLOW_TYPES.map((v) => ({ value: v, label: t(`work_item_type.${v}`) }))}
              data-testid="workflows-type"
            />
          }
          search={
            <Input.Search
              allowClear
              aria-label={t('workflows.search')}
              placeholder={t('workflows.search')}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              data-testid="workflows-search"
            />
          }
        />
      }
    >
      <Table<WorkflowOut>
        rowKey="id"
        data-testid="workflows-table"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 720 }}
        locale={{
          emptyText: loadedEmpty(
            list.isPending,
            t(text === '' ? 'workflows.empty' : 'workflows.no_match'),
          ),
        }}
        columns={[
          {
            key: 'name',
            title: t('workflows.name'),
            render: (_, w) => (
              <Link to={`/admin/workflows/${w.id}`} data-testid={`workflow-link-${w.id}`}>
                <bdi dir="auto">{w.name}</bdi>
              </Link>
            ),
          },
          {
            key: 'state',
            title: t('workflows.state.title'),
            render: (_, w) => <WorkflowState workflow={w} />,
          },
          {
            key: 'version',
            title: t('workflows.published_version'),
            render: (_, w) =>
              w.published_version === null
                ? '—'
                : t('workflows.version_n', { n: w.published_version }),
          },
          {
            key: 'running',
            title: t('workflows.running'),
            align: 'end' as const,
            render: (_, w) => w.running,
          },
          {
            key: 'actions',
            title: <span className="sr-only">{t('settings.actions')}</span>,
            align: 'end' as const,
            render: (_, w) => (
              <RowActions
                rowName={w.name}
                primary={{
                  key: 'open',
                  label: t('workflows.open'),
                  onClick: () => void navigate(`/admin/workflows/${w.id}`),
                  testId: `workflow-open-${w.id}`,
                }}
                more={[
                  {
                    key: 'copy',
                    label: t('workflows.copy'),
                    onClick: () => {
                      setDialog(w);
                    },
                    testId: `workflow-copy-${w.id}`,
                  },
                  {
                    key: 'export',
                    label: t('workflows.export'),
                    onClick: () => {
                      exporting.mutate(w.id, {
                        onSuccess: (file) => {
                          saveFile(w.name, file);
                        },
                        onError: reportError,
                      });
                    },
                    testId: `workflow-export-${w.id}`,
                  },
                  {
                    key: 'delete',
                    label: t('actions.delete'),
                    danger: true,
                    disabled: w.running > 0,
                    whyNot: t('workflows.why.running', { count: w.running }),
                    onClick: () => {
                      void modal.confirm({
                        title: t('workflows.delete_title', { name: w.name }),
                        content: t('workflows.delete_body'),
                        okButtonProps: { danger: true },
                        okText: t('actions.delete'),
                        cancelText: t('actions.cancel'),
                        onOk: () =>
                          remove.mutateAsync({ id: w.id, version: w.version }).then(() => {
                            void message.success(t('workflows.deleted'));
                          }, reportError),
                      });
                    },
                    testId: `workflow-delete-${w.id}`,
                  },
                ]}
              />
            ),
          },
        ]}
      />
      {dialog === 'add' && (
        <AddDialog
          recordType={recordType}
          onClose={() => {
            setDialog(undefined);
          }}
        />
      )}
      {dialog !== undefined && dialog !== 'add' && (
        <CopyDialog
          workflow={dialog}
          onClose={() => {
            setDialog(undefined);
          }}
        />
      )}
    </ListPage>
  );
}
