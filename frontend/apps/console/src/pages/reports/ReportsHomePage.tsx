import { StarFilled, StarOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Card,
  Empty,
  Flex,
  Input,
  List,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import {
  queryKeys,
  useReportFolderChange,
  useReportLibrary,
  useStarReport,
  type ReportFolder,
} from '@supportx/api-client';
import { useIsolate, useLabels } from '@supportx/labels';
import { refreshList, usePersonalChannel, useTenantChannel } from '@supportx/realtime';
import {
  ConflictDialog,
  FormProblem,
  lengthLimit,
  NoAccess,
  useAccess,
  useConflict,
  useFormProblem,
  WriteButton,
} from '@supportx/ui';

import { MyExportsButton, ReportSettingsButton } from './exports';
import { SchedulesButton } from './schedules';

interface Entry {
  ref: string;
  path: string;
  name: string;
  description: string;
  folder: string;
  shared: boolean;
}

const MANAGE_FOLDERS = 'reports.manage_folders';

/**
 * The reports home (REQ-RPT-045): favourites first, built-in reports by module, "My reports",
 * shared folders; one search over names and descriptions in the user's language. Live: a saved or
 * shared report appears and disappears without a refresh.
 */
export function ReportsHomePage() {
  const t = useLabels();
  const { can } = useAccess();
  const allowed = can('reports.view');
  const library = useReportLibrary(allowed);
  const star = useStarReport();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const refresh = () => {
    refreshList(queryClient, queryKeys.reports.library);
  };
  useTenantChannel((message) => {
    if (message.type === 'reports.changed') refresh();
  });
  usePersonalChannel((message) => {
    if (message.type === 'reports.changed') refresh();
  });

  const data = library.data;
  const entries = useMemo<Entry[]>(() => {
    if (data === undefined) return [];
    const folders = new Map(data.folders.map((f) => [f.id, f.name]));
    return [
      ...data.builtin.map((r) => ({
        ref: `builtin:${r.code}`,
        path: `/reports/builtin/${r.code}`,
        name: t(`report.${r.code}`),
        description: t(`report.${r.code}.description`),
        folder: t(`report_folder.${r.folder}`),
        shared: true,
      })),
      ...data.reports.map((r) => ({
        ref: r.id,
        path: `/reports/${r.id}`,
        name: r.name,
        description: r.description ?? '',
        folder:
          r.folder_id === null
            ? t('reports.my_reports')
            : (folders.get(r.folder_id) ?? t('reports.unknown_value')),
        shared: r.folder_id !== null,
      })),
    ];
  }, [data, t]);

  if (!allowed) return <NoAccess titleKey="nav.reports" />;
  const needle = search.trim().toLocaleLowerCase();
  const shown = needle
    ? entries.filter((e) => `${e.name} ${e.description}`.toLocaleLowerCase().includes(needle))
    : entries;
  const starred = new Set(data?.favourites ?? []);
  const sections = new Map<string, Entry[]>();
  const favourites = shown.filter((e) => starred.has(e.ref));
  if (favourites.length > 0) sections.set(t('reports.favourites'), favourites);
  for (const entry of shown)
    sections.set(entry.folder, [...(sections.get(entry.folder) ?? []), entry]);

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('reports.title')}
        </Typography.Title>
        <Space wrap>
          {can(MANAGE_FOLDERS) && <FolderTools folders={data?.folders ?? []} />}
          <MyExportsButton />
          <SchedulesButton />
          <ReportSettingsButton />
        </Space>
      </Flex>
      <Input.Search
        allowClear
        aria-label={t('reports.search')}
        placeholder={t('reports.search')}
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
        }}
        style={{ maxWidth: 360 }}
        data-testid="reports-search"
      />
      {library.isSuccess && shown.length === 0 && (
        <Empty description={t(needle ? 'reports.no_match' : 'reports.empty')} />
      )}
      {[...sections.entries()].map(([title, items]) => (
        <Card key={title} title={title} size="small" data-testid="reports-section">
          <List
            dataSource={items}
            renderItem={(entry) => (
              <List.Item
                actions={[
                  <Button
                    key="star"
                    type="text"
                    aria-label={t(starred.has(entry.ref) ? 'reports.unstar' : 'reports.star')}
                    aria-pressed={starred.has(entry.ref)}
                    icon={starred.has(entry.ref) ? <StarFilled /> : <StarOutlined />}
                    onClick={() => {
                      star.mutate({ ref: entry.ref, starred: !starred.has(entry.ref) });
                    }}
                    data-testid={`reports-star-${entry.ref}`}
                  />,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Link to={entry.path} data-testid={`reports-open-${entry.ref}`}>
                        {entry.name}
                      </Link>
                      {entry.shared && !entry.ref.startsWith('builtin:') && (
                        <Tag>{t('reports.shared')}</Tag>
                      )}
                    </Space>
                  }
                  description={entry.description}
                />
              </List.Item>
            )}
          />
        </Card>
      ))}
    </Space>
  );
}

/** Create, rename and delete shared folders (reports.manage_folders). */
function FolderTools({ folders }: { folders: ReportFolder[] }) {
  const t = useLabels();
  const isolate = useIsolate();
  const change = useReportFolderChange();
  const [open, setOpen] = useState<
    null | { kind: 'create' } | { kind: 'delete'; folder: ReportFolder }
  >(null);
  const [name, setName] = useState('');
  const [moveTo, setMoveTo] = useState('owners');
  const [key] = useState(() => crypto.randomUUID());
  const close = () => {
    problem.clear();
    setOpen(null);
    setName('');
    setMoveTo('owners');
  };
  // A folder someone changed first (409): the shared dialog; "Keep my changes" deletes it anyway.
  const conflict = useConflict();
  // Why a create or delete was refused (a taken name, a permission), at its dialog (D-105).
  const problem = useFormProblem();
  const deleting = open?.kind === 'delete' ? open.folder : undefined;
  const live = folders.find((f) => f.id === deleting?.id);
  const remove = (folder: ReportFolder, version = folder.version) => {
    change.mutate(
      { kind: 'delete', id: folder.id, version, moveTo },
      {
        onSuccess: close,
        onError: (error) => {
          if (!conflict.take(error)) problem.show(error);
        },
      },
    );
  };

  return (
    <Space wrap>
      <WriteButton
        onClick={() => {
          setOpen({ kind: 'create' });
        }}
        data-testid="reports-new-folder"
      >
        {t('reports.new_folder')}
      </WriteButton>
      {folders.length > 0 && (
        <Select
          aria-label={t('reports.delete_folder')}
          placeholder={t('reports.delete_folder')}
          value={null}
          options={folders.map((f) => ({ value: f.id, label: f.name }))}
          onChange={(id: string) => {
            const folder = folders.find((f) => f.id === id);
            if (folder) setOpen({ kind: 'delete', folder });
          }}
          style={{ minWidth: 200 }}
          data-testid="reports-delete-folder"
        />
      )}
      <Modal
        open={open?.kind === 'create'}
        title={t('reports.new_folder')}
        okText={t('reports.create')}
        okButtonProps={{ disabled: name.trim() === '', loading: change.isPending }}
        onCancel={close}
        onOk={() => {
          problem.clear();
          change.mutate(
            { kind: 'create', name: name.trim(), key },
            {
              onSuccess: close,
              onError: (error) => {
                problem.show(error);
              },
            },
          );
        }}
      >
        <Typography.Paragraph type="secondary">
          {t('reports.folder_shared_hint')}
        </Typography.Paragraph>
        <Input
          aria-label={t('reports.folder_name')}
          placeholder={t('reports.folder_name')}
          count={lengthLimit(120)}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
          data-testid="reports-folder-name"
        />
        <FormProblem problem={problem} />
      </Modal>
      <Modal
        open={open?.kind === 'delete'}
        title={
          open?.kind === 'delete'
            ? t('reports.delete_folder_named', { name: isolate(open.folder.name) })
            : ''
        }
        okText={t('reports.delete')}
        okButtonProps={{ danger: true, loading: change.isPending }}
        onCancel={close}
        onOk={() => {
          if (open?.kind !== 'delete') return;
          remove(open.folder);
        }}
      >
        <Typography.Paragraph>{t('reports.move_reports_to')}</Typography.Paragraph>
        <Select
          aria-label={t('reports.move_reports_to')}
          value={moveTo}
          onChange={setMoveTo}
          style={{ width: '100%' }}
          options={[
            { value: 'owners', label: t('reports.move_to_owners') },
            ...folders
              .filter((f) => open?.kind !== 'delete' || f.id !== open.folder.id)
              .map((f) => ({ value: f.id, label: f.name })),
          ]}
          data-testid="reports-move-to"
        />
        <FormProblem problem={problem} />
      </Modal>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={() => t('reports.folder_name')}
        opened={deleting && { name: deleting.name }}
        latest={live && { name: live.name }}
        onReload={() => {
          conflict.clear();
          change.reset();
          close();
        }}
        onKeepMine={() => {
          conflict.clear();
          change.reset();
          if (live !== undefined) remove(live, conflict.latestVersion ?? live.version);
        }}
      />
    </Space>
  );
}
