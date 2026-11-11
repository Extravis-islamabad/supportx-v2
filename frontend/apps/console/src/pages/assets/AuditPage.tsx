import { AuditOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Flex,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Skeleton,
  Table,
  Tabs,
  Typography,
} from 'antd';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  queryKeys,
  useAssetAudit,
  useAssetAuditActions,
  useAssetAuditItems,
  useAssetAuditWork,
  useAssetStates,
  useSession,
  useUnits,
  type AssetAudit,
  type AssetAuditFix,
  type AssetAuditItem,
  type AssetAuditResult,
} from '@supportx/api-client';
import { useJoinParts, useListFormat } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';
import {
  ActionBar,
  EditDrawer,
  FormProblem,
  lengthLimit,
  loadedEmpty,
  NoAccess,
  PresenceAvatars,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  RowActions,
  ToneTag,
  useAccess,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
  usePageCrumbs,
  WriteButton,
  type RecordAction,
} from '@supportx/ui';

import { nameOf } from '../admin/assets/shared';
import { DepartmentPicker, SitePicker, UserPicker } from '../incidents/pickers';
import { AUDIT_STATE_TONES, draftOfAudit, type AuditDraft } from './audits';
import { AuditFields, AuditProgress } from './AuditsPage';
import { okFooter } from './dialogOk';
import { useSiteNames } from './live';
import { problemText } from './problemText';

// One asset audit (WP-049b s3; REQ-AST-042, 043), D-147 template B: its plan, progress and
// items; named auditors mark items while it runs (by scanning or by hand), managers settle the
// discrepancies in bulk (each fix through the asset service, its history naming the audit).
// Live on the audit's own channel: every auditor sees the progress move (043 AC3).

const RESULT_TONES = {
  found: 'success',
  missing: 'error',
  wrong_place: 'warning',
  damaged: 'warning',
} as const;
const MARKS: AssetAuditResult[] = ['found', 'missing', 'damaged', 'wrong_place'];
const FIXES: AssetAuditFix[] = ['move_site', 'change_state', 'assign'];

function ScanBox({ audit }: { audit: AssetAudit }) {
  const t = useLabel();
  const { scan } = useAssetAuditWork(audit.id);
  const [code, setCode] = useState('');
  const [site, setSite] = useState<string | null>(audit.site_ids[0] ?? null);
  const [said, setSaid] = useState<{ ok: boolean; text: string }>();
  const submit = () => {
    if (code.trim() === '') return;
    scan.mutate(
      { code: code.trim(), seenSiteId: site, key: crypto.randomUUID() },
      {
        onSuccess: (item) => {
          setCode('');
          setSaid({
            ok: true,
            text: t('assets.audits.scanned', {
              name: item.tag ?? item.name,
              result: item.result === null ? '' : t(`asset_audit_result.${item.result}`),
            }),
          });
        },
        onError: (error) => {
          setSaid({ ok: false, text: problemText(t, error) ?? '' });
        },
      },
    );
  };
  return (
    <Flex vertical gap={8} data-testid="audit-scan">
      <Flex gap={8} wrap align="end">
        <Form.Item
          label={t('assets.audits.scan_code')}
          htmlFor="audit-scan-code"
          style={{ margin: 0 }}
        >
          <Input
            id="audit-scan-code"
            value={code}
            autoComplete="off"
            onChange={(event) => {
              setCode(event.target.value);
            }}
            onPressEnter={submit}
            style={{ minWidth: 240 }}
            data-testid="audit-scan-code"
          />
        </Form.Item>
        <Form.Item label={t('assets.audits.seen_at')} style={{ margin: 0, minWidth: 200 }}>
          <SitePicker
            value={site}
            onChange={setSite}
            ariaLabel={t('assets.audits.seen_at')}
            placeholder={t('assets.audits.seen_at')}
            testId="audit-scan-site"
          />
        </Form.Item>
        <WriteButton
          type="primary"
          loading={scan.isPending}
          onClick={submit}
          disabled={code.trim() === ''}
          whyDisabled={t('assets.audits.scan_first')}
          data-testid="audit-scan-submit"
        >
          {t('assets.audits.mark_scanned')}
        </WriteButton>
      </Flex>
      {said !== undefined && (
        <Alert
          type={said.ok ? 'success' : 'error'}
          role="status"
          showIcon
          message={said.text}
          data-testid="audit-scan-said"
        />
      )}
    </Flex>
  );
}

function FixDialog({
  audit,
  items,
  open,
  onClose,
}: {
  audit: AssetAudit;
  items: AssetAuditItem[];
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const states = useAssetStates(open);
  const { fix } = useAssetAuditWork(audit.id);
  const [kind, setKind] = useState<AssetAuditFix>('move_site');
  const [site, setSite] = useState<string | null>(
    items.find((i) => i.seen_site_id !== null)?.seen_site_id ?? null,
  );
  const [state, setState] = useState<string>();
  const [holderKind, setHolderKind] = useState<'user' | 'department'>('user');
  const [holder, setHolder] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [result, setResult] = useState<string>();
  const [key] = useState(() => crypto.randomUUID());
  const missing =
    (kind === 'move_site' && site === null) ||
    (kind === 'change_state' && state === undefined) ||
    (kind === 'assign' && holder === null);
  const submit = () => {
    fix.mutate(
      {
        key,
        body: {
          fix: kind,
          item_ids: items.map((i) => i.id),
          site_id: kind === 'move_site' ? site : null,
          state_id: kind === 'change_state' ? (state ?? null) : null,
          holder: kind === 'assign' && holder !== null ? { kind: holderKind, id: holder } : null,
          reason: reason.trim() === '' ? null : reason.trim(),
        },
      },
      {
        onSuccess: (answer) => {
          const refused = answer.outcomes.filter((o) => !o.applied);
          if (refused.length === 0) {
            onClose();
            return;
          }
          setResult(
            t('assets.audits.fix_partly', {
              applied: answer.applied,
              refused: refused.length,
              reason: t(`errors.${refused[0]?.code ?? 'asset_labels_failed'}`),
            }),
          );
        },
        onError: (error) => {
          setResult(problemText(t, error) ?? '');
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      title={t('assets.audits.fix_title', { count: items.length })}
      onCancel={onClose}
      destroyOnHidden
      footer={okFooter({
        okText: t('assets.audits.fix_apply'),
        onOk: submit,
        loading: fix.isPending,
        whyDisabled: missing ? t('assets.audits.fix_choose') : undefined,
        testId: 'audit-fix-apply',
      })}
      data-testid="audit-fix-dialog"
    >
      <Form layout="vertical">
        <Form.Item label={t('assets.audits.fix')}>
          <Segmented
            value={kind}
            onChange={(value) => {
              setKind(value);
            }}
            options={FIXES.map((f) => ({ value: f, label: t(`asset_audit_fix.${f}`) }))}
            data-testid="audit-fix-kind"
          />
        </Form.Item>
        {kind === 'move_site' && (
          <Form.Item label={t('assets.audits.to_site')}>
            <SitePicker
              value={site}
              onChange={setSite}
              ariaLabel={t('assets.audits.to_site')}
              placeholder={t('assets.audits.to_site')}
              testId="audit-fix-site"
            />
          </Form.Item>
        )}
        {kind === 'change_state' && (
          <Form.Item label={t('assets.audits.to_state')} htmlFor="audit-fix-state">
            <Select
              id="audit-fix-state"
              value={state}
              onChange={setState}
              options={(states.data ?? []).map((s) => ({
                value: s.id,
                label: nameOf(s.names, locale),
              }))}
              data-testid="audit-fix-state"
            />
          </Form.Item>
        )}
        {kind === 'assign' && (
          <>
            <Form.Item label={t('assets.audits.assign_to')}>
              <Segmented
                value={holderKind}
                onChange={(value) => {
                  setHolderKind(value);
                  setHolder(null);
                }}
                options={(['user', 'department'] as const).map((k) => ({
                  value: k,
                  label: t(`asset_holder_kind.${k}`),
                }))}
              />
            </Form.Item>
            <Form.Item label={t(`asset_holder_kind.${holderKind}`)}>
              {holderKind === 'user' ? (
                <UserPicker
                  value={holder}
                  onChange={setHolder}
                  ariaLabel={t('asset_holder_kind.user')}
                  testId="audit-fix-user"
                />
              ) : (
                <DepartmentPicker
                  value={holder}
                  onChange={setHolder}
                  ariaLabel={t('asset_holder_kind.department')}
                  testId="audit-fix-department"
                />
              )}
            </Form.Item>
          </>
        )}
        <Form.Item label={t('assets.audits.fix_reason')} htmlFor="audit-fix-reason">
          <Input.TextArea
            id="audit-fix-reason"
            value={reason}
            autoSize={{ minRows: 1, maxRows: 3 }}
            count={lengthLimit(1000)}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
        </Form.Item>
        <Typography.Paragraph type="secondary">{t('assets.audits.fix_note')}</Typography.Paragraph>
      </Form>
      {result !== undefined && (
        <Alert
          type="warning"
          showIcon
          role="status"
          message={result}
          data-testid="audit-fix-said"
        />
      )}
    </Modal>
  );
}

function Items({ audit, discrepancies }: { audit: AssetAudit; discrepancies: boolean }) {
  const t = useLabel();
  const dates = useDateTime();
  const siteName = useSiteNames();
  const items = useAssetAuditItems(audit.id, discrepancies);
  const { mark } = useAssetAuditWork(audit.id);
  const [selected, setSelected] = useState<string[]>([]);
  const [fixing, setFixing] = useState(false);
  const [said, setSaid] = useState<string>();
  const rows = items.data ?? [];
  const settle = discrepancies && audit.may_manage && audit.state === 'running';
  const setResult = (item: AssetAuditItem, result: AssetAuditResult) => {
    setSaid(undefined);
    mark.mutate(
      { id: item.id, version: item.version, result, seenSiteId: item.seen_site_id },
      {
        onError: (error) => {
          setSaid(problemText(t, error) ?? '');
        },
      },
    );
  };
  return (
    <Flex vertical gap={8}>
      {said !== undefined && <Alert type="error" showIcon role="status" message={said} />}
      {settle && (
        <Flex gap={8} align="center" wrap data-testid="audit-fix-bar">
          <Typography.Text>
            {t('assets.bulk_move.selected', { count: selected.length })}
          </Typography.Text>
          <WriteButton
            onClick={() => {
              setFixing(true);
            }}
            disabled={selected.length === 0}
            whyDisabled={t('assets.audits.select_first')}
            data-testid="audit-fix-open"
          >
            {t('assets.audits.fix_open')}
          </WriteButton>
        </Flex>
      )}
      <Table<AssetAuditItem>
        size="small"
        rowKey="id"
        pagination={false}
        loading={items.isPending}
        dataSource={rows}
        scroll={{ x: 'max-content' }}
        rowSelection={
          settle
            ? {
                selectedRowKeys: selected,
                onChange: (keys) => {
                  setSelected(keys.map(String));
                },
                getCheckboxProps: (row) => ({
                  title: t('assets.bulk_move.select_row', { name: row.tag ?? row.name }),
                }),
              }
            : undefined
        }
        locale={{
          emptyText: loadedEmpty(
            items.isPending,
            t(discrepancies ? 'assets.audits.no_discrepancies' : 'assets.audits.no_items'),
          ),
        }}
        data-testid={discrepancies ? 'audit-discrepancies' : 'audit-items'}
        columns={[
          {
            key: 'asset',
            title: t('assets.audits.asset'),
            render: (_, item) => (
              <Flex vertical gap={0}>
                <Link to={`/assets/${item.asset_id}`} data-testid={`audit-item-${item.id}`}>
                  <bdi dir="ltr">{item.tag ?? ''}</bdi>
                </Link>
                <bdi dir="auto">{item.name}</bdi>
              </Flex>
            ),
          },
          {
            key: 'expected',
            title: t('assets.audits.expected_at'),
            render: (_, item) => (
              <Flex vertical gap={0}>
                <bdi dir="auto">{siteName(item.expected_site_id)}</bdi>
                {item.kind === 'unexpected' && (
                  <ToneTag tone="purple">{t('asset_audit_item_kind.unexpected')}</ToneTag>
                )}
              </Flex>
            ),
          },
          {
            key: 'result',
            title: t('assets.audits.result'),
            render: (_, item) =>
              item.result === null ? (
                <Typography.Text type="secondary">{t('assets.audits.not_marked')}</Typography.Text>
              ) : (
                <Flex vertical gap={0}>
                  <ToneTag tone={RESULT_TONES[item.result]} testId={`audit-result-${item.id}`}>
                    {t(`asset_audit_result.${item.result}`)}
                  </ToneTag>
                  {item.seen_site_id !== null && item.seen_site_id !== item.expected_site_id && (
                    <Typography.Text type="secondary">
                      {t('assets.audits.seen_there', { site: siteName(item.seen_site_id) })}
                    </Typography.Text>
                  )}
                </Flex>
              ),
          },
          {
            key: 'marked',
            title: t('assets.audits.marked_by'),
            render: (_, item) =>
              item.marked_at === null ? (
                ''
              ) : (
                <Flex vertical gap={0}>
                  <bdi dir="auto">{item.marked_by?.name ?? ''}</bdi>
                  <Typography.Text type="secondary">
                    {`${t(`asset_audit_method.${item.method ?? 'manual'}`)} · ${dates.format(item.marked_at)}`}
                  </Typography.Text>
                </Flex>
              ),
          },
          {
            key: 'fix',
            title: t('assets.audits.fix'),
            render: (_, item) =>
              item.fix === null ? (
                ''
              ) : (
                <ToneTag tone="info">{t(`asset_audit_fix.${item.fix}`)}</ToneTag>
              ),
          },
          ...(audit.may_mark
            ? [
                {
                  key: 'actions',
                  title: <span className="sr-only">{t('assets.admin.actions')}</span>,
                  render: (_: unknown, item: AssetAuditItem) => (
                    <RowActions
                      rowName={item.tag ?? item.name}
                      primary={{
                        key: 'found',
                        label: t('assets.audits.mark_found'),
                        onClick: () => {
                          setResult(item, 'found');
                        },
                        testId: `audit-mark-found-${item.id}`,
                      }}
                      more={MARKS.filter((m) => m !== 'found').map((m) => ({
                        key: m,
                        label: t(`asset_audit_result.${m}`),
                        onClick: () => {
                          setResult(item, m);
                        },
                        testId: `audit-mark-${m}-${item.id}`,
                      }))}
                    />
                  ),
                },
              ]
            : []),
        ]}
      />
      {fixing && (
        <FixDialog
          audit={audit}
          items={rows.filter((r) => selected.includes(r.id))}
          open={fixing}
          onClose={() => {
            setFixing(false);
            setSelected([]);
          }}
        />
      )}
    </Flex>
  );
}

function EditAuditDrawer({ audit, onClose }: { audit: AssetAudit; onClose: () => void }) {
  const t = useLabel();
  const { update } = useAssetAuditActions();
  const problem = useFormProblem();
  const [draft, setDraft] = useState<AuditDraft>(draftOfAudit(audit));
  const frozen = audit.state !== 'draft';
  const save = () => {
    problem.clear();
    const base = draftOfAudit(audit);
    const changed = Object.fromEntries(
      (Object.keys(draft) as (keyof AuditDraft)[])
        .filter((k) => JSON.stringify(draft[k]) !== JSON.stringify(base[k]))
        .filter((k) => !frozen || ['name', 'description', 'planned_end', 'auditor_ids'].includes(k))
        .map((k) => [k, k === 'description' && draft[k] === '' ? null : draft[k]]),
    );
    update.mutate(
      { id: audit.id, version: audit.version, body: changed },
      { onSuccess: onClose, onError: problem.show },
    );
  };
  return (
    <EditDrawer
      open
      title={t('assets.audits.edit')}
      okText={t('actions.save')}
      saving={update.isPending}
      dirty={JSON.stringify(draft) !== JSON.stringify(draftOfAudit(audit))}
      onOk={save}
      onCancel={onClose}
      testId="audit-edit-drawer"
    >
      <FormProblem problem={problem} />
      <AuditFields draft={draft} onChange={setDraft} scopeFrozen={frozen} known={audit.auditors} />
    </EditDrawer>
  );
}

export function AuditPage() {
  const t = useLabel();
  const { id } = useParams();
  const access = useAccess();
  const dates = useDateTime();
  const queryClient = useQueryClient();
  const allowed = access.can('assets.view');
  const found = useAssetAudit(allowed ? id : undefined);
  const sites = useUnits('sites', allowed);
  const { start, close } = useAssetAuditActions();
  const [editing, setEditing] = useState(false);
  const [said, setSaid] = useState<string>();
  const { modal } = App.useApp();
  const me = useSession().data?.user.id;
  const list = useListFormat();
  const joinParts = useJoinParts();
  const viewers = useRecordChannel('asset_audit', allowed ? id : undefined, () => {
    if (id === undefined) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.audit(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.auditItemsAll(id) });
  });
  usePageCrumbs([
    { label: t('assets.audits.title'), path: '/assets/audits' },
    ...(found.data ? [{ label: found.data.display_id }] : []),
  ]);
  if (!allowed) return <NoAccess titleKey="nav.assets" />;
  if (found.isPending) return <Skeleton active />;
  const audit = found.data;
  if (audit === undefined) {
    return <Alert type="warning" showIcon message={t('errors.asset_audit_not_found')} />;
  }
  const manage = audit.may_manage;
  const closed = audit.state === 'closed';
  const managerOnly = t('assets.audits.manage_needed');
  const move = (which: typeof start) => {
    setSaid(undefined);
    which.mutate(
      { id: audit.id, version: audit.version },
      {
        onError: (error) => {
          setSaid(problemText(t, error) ?? '');
        },
      },
    );
  };
  const actions: RecordAction[] = [
    {
      key: 'start',
      label: t('assets.audits.start'),
      allowed: manage && audit.state === 'draft',
      whyNot: manage ? t('assets.audits.already_started') : managerOnly,
      primary: audit.state === 'draft',
      rank: 1,
      onClick: () => {
        modal.confirm({
          title: t('assets.audits.start_confirm'),
          content: t(
            audit.kind === 'self' ? 'assets.audits.start_self_note' : 'assets.audits.start_note',
          ),
          okText: t('assets.audits.start'),
          onOk: () => {
            move(start);
          },
        });
      },
      testId: 'audit-start',
    },
    {
      key: 'close',
      label: t('assets.audits.close'),
      allowed: manage && audit.state === 'running',
      whyNot: manage ? t('assets.audits.not_running') : managerOnly,
      primary: audit.state === 'running',
      rank: 2,
      onClick: () => {
        modal.confirm({
          title: t('assets.audits.close_confirm'),
          content: t('assets.audits.close_note'),
          okText: t('assets.audits.close'),
          onOk: () => {
            move(close);
          },
        });
      },
      testId: 'audit-close',
    },
    {
      key: 'edit',
      label: t('actions.edit'),
      allowed: manage && !closed,
      whyNot: closed ? t('assets.audits.closed_read_only') : managerOnly,
      rank: 3,
      onClick: () => {
        setEditing(true);
      },
      testId: 'audit-edit',
    },
  ];
  const siteNames = audit.site_ids
    .map((s) => sites.data?.find((x) => x.id === s)?.name ?? '')
    .filter((n) => n !== '');
  return (
    <RecordPage
      testId="asset-audit-page"
      header={
        <RecordHeader
          icon={<AuditOutlined />}
          kind="asset"
          typeLabel={t('assets.audits.record_type')}
          displayId={audit.display_id}
          copyable
          title={audit.name}
          extra={<PresenceAvatars viewers={viewers} selfUserId={me ?? null} />}
          testIds={{ id: 'audit-display-id', title: 'audit-heading' }}
          tags={
            <ToneTag tone={AUDIT_STATE_TONES[audit.state]} testId="audit-state">
              {t(`asset_audit_state.${audit.state}`)}
            </ToneTag>
          }
        />
      }
      actions={<ActionBar actions={actions} max={2} testId="audit-actions" />}
      alerts={
        <>
          {closed && (
            <Alert
              type="info"
              showIcon
              role="status"
              message={t('assets.audits.closed_read_only')}
            />
          )}
          {said !== undefined && (
            <Alert type="error" showIcon role="status" message={said} data-testid="audit-said" />
          )}
        </>
      }
      panel={
        <PropertiesPanel
          testId="audit-panel"
          sections={[
            {
              key: 'details',
              title: t('assets.record.details'),
              children: (
                <PropertyList
                  testId="audit-props"
                  items={[
                    {
                      key: 'kind',
                      label: t('assets.audits.kind'),
                      content: t(`asset_audit_kind.${audit.kind}`),
                      filled: true,
                    },
                    {
                      key: 'progress',
                      label: t('assets.audits.progress'),
                      content:
                        audit.state === 'draft' ? (
                          t('assets.audits.not_started')
                        ) : (
                          <span data-testid="audit-progress">
                            <AuditProgress audit={audit} />
                          </span>
                        ),
                      filled: true,
                    },
                    {
                      key: 'discrepancies',
                      label: t('assets.audits.discrepancies'),
                      content: String(audit.progress.discrepancies),
                      filled: audit.state !== 'draft',
                    },
                    {
                      key: 'sites',
                      label: t('assets.audits.sites'),
                      content: (
                        <bdi dir="auto">
                          {siteNames.length === 0 ? t('assets.audits.any_site') : list(siteNames)}
                        </bdi>
                      ),
                      filled: true,
                    },
                    {
                      key: 'planned',
                      label: t('assets.audits.planned'),
                      content: joinParts(
                        [audit.planned_start, audit.planned_end]
                          .map((d) => (d === null ? '' : dates.formatDay(d)))
                          .filter((d) => d !== ''),
                        ' – ',
                      ),
                      filled: audit.planned_start !== null || audit.planned_end !== null,
                    },
                    {
                      key: 'auditors',
                      label: t('assets.audits.auditors'),
                      content: (
                        <bdi dir="auto">{list(audit.auditors.map((a) => a.name ?? ''))}</bdi>
                      ),
                      filled: audit.auditors.length > 0,
                    },
                    {
                      key: 'description',
                      label: t('assets.audits.description'),
                      content: <bdi dir="auto">{audit.description ?? ''}</bdi>,
                      filled: audit.description !== null,
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      }
    >
      {editing && (
        <EditAuditDrawer
          audit={audit}
          onClose={() => {
            setEditing(false);
          }}
        />
      )}
      {audit.state === 'draft' ? (
        <Alert type="info" showIcon message={t('assets.audits.draft_note')} />
      ) : (
        <Tabs
          items={[
            {
              key: 'items',
              label: t('assets.audits.items'),
              children: (
                <Flex vertical gap={16}>
                  {audit.may_mark && <ScanBox audit={audit} />}
                  <Items audit={audit} discrepancies={false} />
                </Flex>
              ),
            },
            {
              key: 'discrepancies',
              label: t('assets.audits.discrepancies'),
              children: <Items audit={audit} discrepancies />,
            },
          ]}
          data-testid="audit-tabs"
        />
      )}
    </RecordPage>
  );
}
