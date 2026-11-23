import {
  DatePicker,
  Flex,
  Form,
  Input,
  Progress,
  Segmented,
  Select,
  Table,
  TreeSelect,
  Typography,
} from 'antd';
import dayjs from 'dayjs';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  useAssetAuditActions,
  useAssetAudits,
  useAssetGroups,
  useAssetProductTypes,
  useUnits,
  useUsers,
  type AssetAudit,
  type AssetAuditKind,
  type AssetAuditState,
} from '@supportx/api-client';
import { useJoinParts } from '@supportx/labels';
import {
  CellText,
  EditDrawer,
  FilterBar,
  FormProblem,
  lengthLimit,
  ListPage,
  loadedEmpty,
  NoAccess,
  PageHeader,
  ToneTag,
  useAccess,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { nameOf } from '../admin/assets/shared';
import { typeTree, type TypeNode } from '../admin/assets/tree';
import {
  AUDIT_STATE_TONES,
  bodyOfAudit,
  draftOfAudit,
  useAuditsLive,
  type AuditDraft,
} from './audits';

const KINDS: AssetAuditKind[] = ['technician', 'self'];
const NAME_MAX = 200;
const TEXT_MAX = 10000;

// Asset audits (WP-049b s3; REQ-AST-042, 043): the list (D-147 template A) and the plan form.
// Live: every audit change reaches the tenant channel as an ID (`assets.audits_changed`), and
// the list refetches through the API, which shows each person only the audits they may open.

/** People to name as auditors: staff found by name (server search). */
export function AuditorPicker({
  value,
  onChange,
  known,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  known?: { id: string; name: string | null }[];
}) {
  const t = useLabel();
  const [search, setSearch] = useState('');
  const searched = useDebounced(search, 250);
  const users = useUsers({ q: searched, sort: 'display_name', limit: 20 });
  const options = useMemo(() => {
    const found = (users.data?.pages.flatMap((p) => p.items) ?? [])
      .filter((u) => u.user_type === 'technician')
      .map((u) => ({ value: u.id, label: u.display_name }));
    for (const person of known ?? []) {
      if (!found.some((o) => o.value === person.id)) {
        found.push({ value: person.id, label: person.name ?? '' });
      }
    }
    return found;
  }, [users.data, known]);
  return (
    <Select
      id="audit-auditors"
      mode="multiple"
      showSearch
      filterOption={false}
      onSearch={setSearch}
      value={value}
      onChange={onChange}
      options={options}
      placeholder={t('assets.audits.auditors_placeholder')}
      aria-label={t('assets.audits.auditors')}
      data-testid="audit-auditors"
    />
  );
}

/** The plan's fields: what, who, where, when. A running audit keeps its scope. */
export function AuditFields({
  draft,
  onChange,
  scopeFrozen = false,
  known,
}: {
  draft: AuditDraft;
  onChange: (draft: AuditDraft) => void;
  scopeFrozen?: boolean;
  known?: { id: string; name: string | null }[];
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const sites = useUnits('sites');
  const types = useAssetProductTypes();
  const groups = useAssetGroups();
  const tree = useMemo(() => typeTree(types.data ?? []), [types.data]);
  const choices = (nodes: TypeNode[]): object[] =>
    nodes.map((node) => ({
      value: node.id,
      title: nameOf(node.names, locale),
      children: choices(node.children ?? []),
    }));
  const set = (patch: Partial<AuditDraft>) => {
    onChange({ ...draft, ...patch });
  };
  return (
    <Form layout="vertical">
      <Form.Item label={t('assets.audits.name')} htmlFor="audit-name" required>
        <Input
          id="audit-name"
          value={draft.name}
          count={lengthLimit(NAME_MAX)}
          onChange={(event) => {
            set({ name: event.target.value });
          }}
          data-testid="audit-name"
        />
      </Form.Item>
      <Form.Item label={t('assets.audits.kind')}>
        <Segmented
          value={draft.kind}
          disabled={scopeFrozen}
          onChange={(value) => {
            set({ kind: value });
          }}
          options={KINDS.map((k) => ({ value: k, label: t(`asset_audit_kind.${k}`) }))}
          data-testid="audit-kind"
        />
      </Form.Item>
      <Form.Item label={t('assets.audits.description')} htmlFor="audit-description">
        <Input.TextArea
          id="audit-description"
          value={draft.description}
          count={lengthLimit(TEXT_MAX)}
          autoSize={{ minRows: 2, maxRows: 5 }}
          onChange={(event) => {
            set({ description: event.target.value });
          }}
        />
      </Form.Item>
      <Typography.Text type="secondary">
        {t(scopeFrozen ? 'assets.audits.scope_frozen' : 'assets.audits.scope_help')}
      </Typography.Text>
      <Form.Item label={t('assets.audits.sites')} htmlFor="audit-sites">
        <Select
          id="audit-sites"
          mode="multiple"
          disabled={scopeFrozen}
          value={draft.site_ids}
          onChange={(ids: string[]) => {
            set({ site_ids: ids });
          }}
          options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
          placeholder={t('assets.audits.any_site')}
          data-testid="audit-sites"
        />
      </Form.Item>
      <Form.Item label={t('assets.audits.product_types')} htmlFor="audit-types">
        <TreeSelect
          id="audit-types"
          multiple
          disabled={scopeFrozen}
          value={draft.product_type_ids}
          treeData={choices(tree)}
          onChange={(ids: string[]) => {
            set({ product_type_ids: ids });
          }}
          placeholder={t('assets.audits.any_type')}
          data-testid="audit-types"
        />
      </Form.Item>
      <Form.Item label={t('assets.audits.groups')} htmlFor="audit-groups">
        <Select
          id="audit-groups"
          mode="multiple"
          disabled={scopeFrozen}
          value={draft.group_ids}
          onChange={(ids: string[]) => {
            set({ group_ids: ids });
          }}
          options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
          placeholder={t('assets.audits.any_group')}
          data-testid="audit-groups"
        />
      </Form.Item>
      <Form.Item label={t('assets.audits.planned')}>
        <DatePicker.RangePicker
          allowEmpty={[true, true]}
          disabled={[scopeFrozen, false]}
          value={[
            draft.planned_start === null ? null : dayjs(draft.planned_start),
            draft.planned_end === null ? null : dayjs(draft.planned_end),
          ]}
          onChange={(range) => {
            set({
              planned_start: range?.[0]?.format('YYYY-MM-DD') ?? null,
              planned_end: range?.[1]?.format('YYYY-MM-DD') ?? null,
            });
          }}
          aria-label={t('assets.audits.planned')}
          data-testid="audit-planned"
        />
      </Form.Item>
      <Form.Item label={t('assets.audits.auditors')} htmlFor="audit-auditors">
        <AuditorPicker
          value={draft.auditor_ids}
          onChange={(ids) => {
            set({ auditor_ids: ids });
          }}
          known={known}
        />
      </Form.Item>
    </Form>
  );
}

function PlanAuditDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const navigate = useNavigate();
  const { create } = useAssetAuditActions();
  const problem = useFormProblem();
  const [draft, setDraft] = useState(draftOfAudit());
  const [key] = useState(() => crypto.randomUUID());
  const save = () => {
    problem.clear();
    create.mutate(
      { key, body: bodyOfAudit(draft) },
      {
        onSuccess: (made) => {
          onClose();
          void navigate(`/assets/audits/${made.id}`);
        },
        onError: problem.show,
      },
    );
  };
  return (
    <EditDrawer
      open={open}
      title={t('assets.audits.plan')}
      okText={t('assets.audits.plan_save')}
      okDisabled={draft.name.trim() === ''}
      okWhyNot={t('assets.audits.name_first')}
      saving={create.isPending}
      dirty={draft.name !== '' || draft.auditor_ids.length > 0}
      onOk={save}
      onCancel={onClose}
      testId="audit-plan-drawer"
    >
      <FormProblem problem={problem} />
      <AuditFields draft={draft} onChange={setDraft} />
    </EditDrawer>
  );
}

/**
 * found / expected, as a bar (REQ-AST-043 AC3). The fill is the found share only, so it matches
 * the "1 of 6 found" beside it (QA 2026-11-11 V-15: the marked share made it look half done);
 * how many are marked stays in its accessible name.
 */
export function AuditProgress({ audit }: { audit: AssetAudit }) {
  const t = useLabel();
  const { expected, found, marked } = audit.progress;
  return (
    <Flex gap={8} align="center" style={{ minWidth: 160 }}>
      <Progress
        percent={expected === 0 ? 0 : Math.round((found / expected) * 100)}
        size="small"
        showInfo={false}
        style={{ flex: 1 }}
        aria-label={t('assets.audits.progress_label', { found, marked, expected })}
      />
      <Typography.Text>{t('assets.audits.found_of', { found, expected })}</Typography.Text>
    </Flex>
  );
}

const STATES: (AssetAuditState | 'all')[] = ['all', 'draft', 'running', 'closed'];

export function AuditsPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const access = useAccess();
  const dates = useDateTime();
  const joinParts = useJoinParts();
  const allowed = access.can('assets.view');
  const list = useAssetAudits();
  const [state, setState] = useState<AssetAuditState | 'all'>('all');
  const [search, setSearch] = useState('');
  const [planning, setPlanning] = useState(false);
  useAuditsLive();
  if (!allowed) return <NoAccess titleKey="nav.assets" />;
  const needle = search.trim().toLowerCase();
  const rows = (list.data ?? []).filter(
    (a) =>
      (state === 'all' || a.state === state) &&
      (needle === '' ||
        a.name.toLowerCase().includes(needle) ||
        a.display_id.toLowerCase().includes(needle)),
  );
  const manage = access.can('assets.manage');
  return (
    <ListPage
      testId="asset-audits-page"
      header={
        <PageHeader
          title={t('assets.audits.title')}
          count={list.data === undefined ? undefined : String(rows.length)}
          back={{ label: t('nav.assets'), onClick: () => void navigate('/assets') }}
          extra={
            manage && (
              <WriteButton
                type="primary"
                onClick={() => {
                  setPlanning(true);
                }}
                data-testid="audit-plan-open"
              >
                {t('assets.audits.plan')}
              </WriteButton>
            )
          }
        />
      }
      filters={
        <FilterBar
          testId="asset-audits-filterbar"
          view={
            <Segmented
              value={state}
              onChange={(value) => {
                setState(value);
              }}
              options={STATES.map((s) => ({
                value: s,
                label: s === 'all' ? t('assets.audits.all') : t(`asset_audit_state.${s}`),
              }))}
              data-testid="asset-audits-state"
            />
          }
          search={
            <Input.Search
              allowClear
              aria-label={t('assets.audits.search')}
              placeholder={t('assets.audits.search')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
              data-testid="asset-audits-search"
            />
          }
        />
      }
    >
      <Table<AssetAudit>
        size="small"
        rowKey="id"
        loading={list.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{
          emptyText: loadedEmpty(
            list.isPending,
            t(manage ? 'assets.audits.none' : 'assets.audits.none_yours'),
          ),
        }}
        data-testid="asset-audits"
        onRow={(audit) => ({
          onClick: () => void navigate(`/assets/audits/${audit.id}`),
          style: { cursor: 'pointer' },
        })}
        columns={[
          {
            key: 'id',
            title: t('assets.audits.id'),
            render: (_, audit) => (
              <Link to={`/assets/audits/${audit.id}`} data-testid={`audit-row-${audit.id}`}>
                <bdi dir="ltr">{audit.display_id}</bdi>
              </Link>
            ),
          },
          {
            key: 'name',
            title: t('assets.audits.name'),
            render: (_, audit) => (
              <CellText title={audit.name}>
                <bdi dir="auto">{audit.name}</bdi>
              </CellText>
            ),
          },
          {
            key: 'kind',
            title: t('assets.audits.kind'),
            render: (_, audit) => t(`asset_audit_kind.${audit.kind}`),
          },
          {
            key: 'state',
            title: t('assets.audits.state'),
            render: (_, audit) => (
              <ToneTag tone={AUDIT_STATE_TONES[audit.state]}>
                {t(`asset_audit_state.${audit.state}`)}
              </ToneTag>
            ),
          },
          {
            key: 'progress',
            title: t('assets.audits.progress'),
            render: (_, audit) =>
              audit.state === 'draft' ? (
                <Typography.Text type="secondary">{t('assets.audits.not_started')}</Typography.Text>
              ) : (
                <AuditProgress audit={audit} />
              ),
          },
          {
            key: 'planned',
            title: t('assets.audits.planned'),
            render: (_, audit) =>
              joinParts(
                [audit.planned_start, audit.planned_end]
                  .map((d) => (d === null ? '' : dates.formatDay(d)))
                  .filter((d) => d !== ''),
                ' – ',
              ),
          },
        ]}
      />
      {planning && (
        <PlanAuditDrawer
          open={planning}
          onClose={() => {
            setPlanning(false);
          }}
        />
      )}
    </ListPage>
  );
}
