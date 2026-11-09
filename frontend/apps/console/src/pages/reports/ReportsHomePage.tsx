import { useQueryClient } from '@tanstack/react-query';
import { Input, Modal, Select, Space, Tag, Typography } from 'antd';
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
  LibraryPage,
  NoAccess,
  PageHeader,
  useAccess,
  useConflict,
  useFormProblem,
  WriteButton,
  type LibraryGroup,
  type LibraryItem,
} from '@supportx/ui';

import { MyExportsButton, ReportSettingsButton } from './exports';
import { SchedulesButton } from './schedules';

interface Entry {
  ref: string;
  path: string;
  name: string;
  description: string;
  module: string;
  /** Where a saved report lives: "My reports" or its shared folder. */
  place?: string;
  shared: boolean;
}

const MANAGE_FOLDERS = 'reports.manage_folders';

/**
 * Every module's tab, in this order, even before a module has reports (D-147: reports of every
 * module): a built-in report's folder is its module; a saved report goes by its entity.
 */
const MODULES = [
  'incidents',
  'service_requests',
  'problems',
  'changes',
  'releases',
  'assets',
] as const;
const MODULE_OF_ENTITY: Record<string, string> = {
  incident: 'incidents',
  service_request: 'service_requests',
  problem: 'problems',
  change: 'changes',
  release: 'releases',
  asset: 'assets',
};
/** Modules whose reporting data has not arrived yet: their tab says so. */
const COMING = new Set(['changes', 'assets']);

/**
 * The reports home on template D (REQ-RPT-045, D-147): search and favourites on top, then one
 * tab per module with its built-in and saved reports; one search over names and descriptions in
 * the user's language. Live: a saved or shared report appears and disappears without a refresh.
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
        module: r.folder,
        shared: true,
      })),
      ...data.reports.map((r) => ({
        ref: r.id,
        path: `/reports/${r.id}`,
        name: r.name,
        description: r.description ?? '',
        module: MODULE_OF_ENTITY[r.definition.entity] ?? r.definition.entity,
        place:
          r.folder_id === null
            ? t('reports.my_reports')
            : (folders.get(r.folder_id) ?? t('reports.unknown_value')),
        shared: r.folder_id !== null,
      })),
    ];
  }, [data, t]);

  const groups = useMemo<LibraryGroup[]>(() => {
    const item = (entry: Entry): LibraryItem => ({
      key: entry.ref,
      searchText: `${entry.name} ${entry.description}`,
      title: (
        <Link to={entry.path} data-testid={`reports-open-${entry.ref}`}>
          {entry.name}
        </Link>
      ),
      description: entry.description === '' ? undefined : entry.description,
      tags:
        entry.shared && !entry.ref.startsWith('builtin:') ? (
          <Tag>{t('reports.shared')}</Tag>
        ) : undefined,
      meta: entry.place,
      testId: `reports-item-${entry.ref}`,
    });
    const known = new Set<string>(MODULES);
    const extra = [...new Set(entries.map((e) => e.module))].filter((m) => !known.has(m));
    return [...MODULES, ...extra].map((module) => ({
      key: module,
      label: t(`report_folder.${module}`),
      items: entries.filter((e) => e.module === module).map(item),
      empty: t(COMING.has(module) ? `reports.module_coming.${module}` : 'reports.module_none'),
    }));
  }, [entries, t]);

  if (!allowed) return <NoAccess titleKey="nav.reports" />;
  const favourites = new Set(data?.favourites ?? []);

  return (
    <LibraryPage
      testId="reports"
      header={
        <PageHeader
          title={t('reports.title')}
          count={library.isSuccess ? String(entries.length) : undefined}
          extra={
            <>
              {can(MANAGE_FOLDERS) && <FolderTools folders={data?.folders ?? []} />}
              <MyExportsButton />
              <SchedulesButton />
              <ReportSettingsButton />
            </>
          }
        />
      }
      groups={groups}
      search={search}
      onSearch={setSearch}
      searchLabel={t('reports.search')}
      favourites={favourites}
      onStar={(ref, starred) => {
        star.mutate({ ref, starred });
      }}
      loading={!library.isSuccess}
    />
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
