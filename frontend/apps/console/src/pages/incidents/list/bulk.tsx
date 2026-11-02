import {
  Alert,
  Button,
  Checkbox,
  Drawer,
  Flex,
  Input,
  List,
  Modal,
  Progress,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  useBulkJob,
  useBulkJobs,
  useIncidentAssignees,
  useIncidentCatalogue,
  useStartBulk,
  type BulkAction,
  type BulkJob,
  type BulkRequest,
} from '@supportx/api-client';
import {
  lengthLimit,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { BULK_ACTIONS, BULK_MAX, skipReason, type Selection } from './model';

import { CategoryCascade } from '../CategoryCascade';
import { closureCodeChoices, listValueLabel, scaleLabel } from '../labels';
import { GroupPicker, SitePicker } from '../pickers';

// Select across pages and bulk changes (REQ-INC-119, 120). Up to 1,000 records run as a background
// job as you: each record keeps its own permissions, transitions and closure rules, and one that
// refuses is skipped with the reason in words (AC1). Progress is live, and the result stays
// findable after leaving the page (AC3).

const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;

/** The bar above the table: what is selected, "select all N", and the bulk actions (AC2). */
export function BulkBar({
  selection,
  onSelection,
  pageCount,
  total,
  capped,
  onAction,
  canEdit,
}: {
  selection: Selection;
  onSelection: (selection: Selection) => void;
  pageCount: number;
  total: number | null;
  capped: boolean;
  onAction: (action: BulkAction) => void;
  canEdit: (action: BulkAction) => boolean;
}) {
  const t = useLabel();
  const count = selection.all ? (total ?? 0) : selection.ids.length;
  const nothing = count === 0;
  const pageAll = !selection.all && selection.ids.length > 0 && selection.ids.length === pageCount;
  const more = total !== null && total > pageCount;
  const tooMany = selection.all && (capped || (total ?? 0) > BULK_MAX);
  return (
    <Flex gap={12} wrap align="center" role="region" aria-label={t('incidents.bulk.region')}>
      <Typography.Text data-testid="inc-selected" aria-live="polite">
        {selection.all
          ? t(capped ? 'incidents.bulk.all_selected_capped' : 'incidents.bulk.all_selected', {
              count: total ?? 0,
            })
          : t('incidents.bulk.selected', { count })}
      </Typography.Text>
      {pageAll && more && (
        <Button
          type="link"
          onClick={() => {
            onSelection({ ids: [], all: true });
          }}
          data-testid="inc-select-all"
        >
          {t(capped ? 'incidents.bulk.select_all_capped' : 'incidents.bulk.select_all', {
            count: total,
          })}
        </Button>
      )}
      {!nothing && (
        <Button
          type="link"
          onClick={() => {
            onSelection({ ids: [], all: false });
          }}
          data-testid="inc-select-none"
        >
          {t('incidents.bulk.clear')}
        </Button>
      )}
      <Space wrap>
        {BULK_ACTIONS.filter(canEdit).map((action) => {
          const why = nothing
            ? t('incidents.bulk.select_first')
            : tooMany
              ? t('incidents.bulk.too_many', { max: BULK_MAX })
              : undefined;
          return (
            // Disabled with the reason, never a blocking alert (REQ-INC-119 AC2).
            <Tooltip key={action} title={why}>
              <span>
                <WriteButton
                  disabled={why !== undefined}
                  onClick={() => {
                    onAction(action);
                  }}
                  data-testid={`inc-bulk-${action}`}
                >
                  {t(`incidents.bulk.action.${action}`)}
                </WriteButton>
              </span>
            </Tooltip>
          );
        })}
      </Space>
    </Flex>
  );
}

/** Plain text as the paragraphs of a rich text value (the server sanitises it again). */
function paragraphs(text: string): string {
  const escape = (line: string) =>
    line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return text
    .split(/\n{2,}/)
    .filter((part) => part.trim() !== '')
    .map((part) => `<p>${part.split('\n').map(escape).join('<br>')}</p>`)
    .join('');
}

type EditField = 'impact' | 'urgency' | 'priority' | 'category_id' | 'level' | 'site_id';
const EDIT_FIELDS: readonly EditField[] = [
  'impact',
  'urgency',
  'priority',
  'category_id',
  'level',
  'site_id',
];

/** The dialog of one bulk action: only what the user sets is sent (REQ-INC-120 AC2). */
export function BulkDialog({
  action,
  count,
  request,
  onClose,
  onStarted,
}: {
  action: BulkAction | null;
  count: number;
  request: Omit<BulkRequest, 'action' | 'changes'>;
  onClose: () => void;
  onStarted: (job: BulkJob) => void;
}) {
  const t = useLabel();
  const start = useStartBulk();
  const { locale } = useAppearance();
  const catalogue = useIncidentCatalogue(action !== null);
  const [included, setIncluded] = useState<EditField[]>([]);
  const [values, setValues] = useState<Record<string, string | null>>({});
  const [reason, setReason] = useState('');
  const [groupId, setGroupId] = useState<string | null>(null);
  const [technicianId, setTechnicianId] = useState<string | null>(null);
  const [loseAccess, setLoseAccess] = useState(false);
  const [resolution, setResolution] = useState('');
  const [closureCode, setClosureCode] = useState<string | null>(null);
  const [openWork, setOpenWork] = useState(false);
  const assignees = useIncidentAssignees(groupId, '', action === 'assign');
  if (action === null) return null;

  const set = (name: string, value: string | null) => {
    setValues({ ...values, [name]: value });
  };
  const changes = (): Record<string, unknown> => {
    switch (action) {
      case 'edit': {
        const sent: Record<string, unknown> = {};
        for (const name of included) sent[name] = values[name] ?? null;
        if (included.includes('priority')) sent.priority_reason = reason.trim();
        return sent;
      }
      case 'assign':
        return {
          group_id: groupId,
          technician_id: technicianId,
          confirm_lose_access: loseAccess,
        };
      case 'take':
        return {};
      case 'resolve':
        return {
          ...(resolution.trim() === '' ? {} : { resolution: paragraphs(resolution) }),
          confirm_open_work: openWork,
        };
      case 'close':
        return {
          ...(closureCode === null ? {} : { closure_code: closureCode }),
          confirm_open_work: openWork,
        };
    }
  };
  const missing =
    (action === 'edit' && included.length === 0) ||
    (action === 'edit' && included.includes('priority') && reason.trim() === '') ||
    (action === 'assign' && groupId === null && technicianId === null);

  const scaleOptions = (scale: 'impact' | 'urgency') =>
    (catalogue.data?.scales ?? [])
      .filter((v) => v.scale === scale)
      .map((v) => ({ value: v.code, label: scaleLabel(t, catalogue.data, scale, v.code, locale) }));
  const editor = (name: EditField) => {
    const testId = `inc-bulk-value-${name}`;
    const label = t(`work_item.field.${name}`);
    switch (name) {
      case 'impact':
      case 'urgency':
        return (
          <Select
            aria-label={label}
            value={values[name] ?? undefined}
            onChange={(v: string) => {
              set(name, v);
            }}
            options={scaleOptions(name)}
            style={{ minWidth: 200 }}
            data-testid={testId}
          />
        );
      case 'priority':
        return (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Select
              aria-label={label}
              value={values.priority ?? undefined}
              onChange={(v: string) => {
                set('priority', v);
              }}
              options={PRIORITIES.map((p) => ({
                value: p,
                label: scaleLabel(t, catalogue.data, 'priority', p, locale),
              }))}
              style={{ minWidth: 200 }}
              data-testid={testId}
            />
            <Input
              aria-label={t('incidents.bulk.priority_reason')}
              placeholder={t('incidents.bulk.priority_reason')}
              value={reason}
              count={lengthLimit(500)}
              onChange={(event) => {
                setReason(event.target.value);
              }}
              data-testid="inc-bulk-priority-reason"
            />
          </Space>
        );
      case 'category_id':
        return (
          <CategoryCascade
            value={values.category_id ?? null}
            onChange={(v) => {
              set('category_id', v);
            }}
            testId={testId}
          />
        );
      case 'level':
        return (
          <Select
            aria-label={label}
            allowClear
            value={values.level ?? undefined}
            onChange={(v: string | undefined) => {
              set('level', v ?? null);
            }}
            options={(catalogue.data?.levels ?? []).map((v) => ({
              value: v.code,
              label: listValueLabel(t, 'level', v, locale),
            }))}
            style={{ minWidth: 200 }}
            data-testid={testId}
          />
        );
      case 'site_id':
        return (
          <SitePicker
            value={values.site_id ?? null}
            onChange={(v) => {
              set('site_id', v);
            }}
            testId={testId}
            ariaLabel={label}
          />
        );
    }
  };

  return (
    <Modal
      open
      title={t(`incidents.bulk.title.${action}`, { count })}
      onCancel={onClose}
      okText={t('incidents.bulk.start')}
      cancelText={t('incidents.bulk.cancel')}
      okButtonProps={{
        disabled: missing,
        loading: start.isPending,
        'data-testid': 'inc-bulk-start',
      }}
      onOk={() => {
        start.mutate(
          { ...request, action, changes: changes() },
          {
            onSuccess: (job) => {
              onStarted(job);
            },
            onError: reportError,
          },
        );
      }}
      data-testid="inc-bulk-dialog"
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Alert type="info" showIcon message={t('incidents.bulk.as_you')} />
        {action === 'edit' && (
          <>
            <Typography.Text>{t('incidents.bulk.edit_hint')}</Typography.Text>
            {EDIT_FIELDS.map((name) => (
              <Space key={name} direction="vertical" style={{ width: '100%' }}>
                <Checkbox
                  checked={included.includes(name)}
                  onChange={(event) => {
                    setIncluded(
                      event.target.checked
                        ? [...included, name]
                        : included.filter((f) => f !== name),
                    );
                  }}
                  data-testid={`inc-bulk-field-${name}`}
                >
                  {t(`work_item.field.${name}`)}
                </Checkbox>
                {included.includes(name) && editor(name)}
              </Space>
            ))}
          </>
        )}
        {action === 'assign' && (
          <>
            <GroupPicker
              value={groupId}
              onChange={(v) => {
                setGroupId(v);
                setTechnicianId(null);
              }}
              testId="inc-bulk-group"
              ariaLabel={t('work_item.field.group_id')}
            />
            <Select
              aria-label={t('work_item.field.technician_id')}
              placeholder={t('work_item.field.technician_id')}
              allowClear
              value={technicianId ?? undefined}
              onChange={(v: string | undefined) => {
                setTechnicianId(v ?? null);
              }}
              options={(assignees.data ?? []).map((a) => ({ value: a.id, label: a.display_name }))}
              data-testid="inc-bulk-technician"
            />
            <Checkbox
              checked={loseAccess}
              onChange={(event) => {
                setLoseAccess(event.target.checked);
              }}
            >
              {t('incidents.bulk.lose_access')}
            </Checkbox>
          </>
        )}
        {action === 'take' && <Typography.Text>{t('incidents.bulk.take_hint')}</Typography.Text>}
        {action === 'resolve' && (
          <Input.TextArea
            aria-label={t('work_item.field.resolution')}
            placeholder={t('incidents.bulk.resolution_hint')}
            value={resolution}
            rows={4}
            onChange={(event) => {
              setResolution(event.target.value);
            }}
            data-testid="inc-bulk-resolution"
          />
        )}
        {action === 'close' && (
          <Select
            aria-label={t('work_item.field.closure_code')}
            placeholder={t('incidents.bulk.keep_closure_code')}
            allowClear
            value={closureCode ?? undefined}
            onChange={(v: string | undefined) => {
              setClosureCode(v ?? null);
            }}
            options={closureCodeChoices(t, catalogue.data, locale)}
            data-testid="inc-bulk-closure-code"
          />
        )}
        {(action === 'resolve' || action === 'close') && (
          <Checkbox
            checked={openWork}
            onChange={(event) => {
              setOpenWork(event.target.checked);
            }}
          >
            {t('incidents.bulk.open_work')}
          </Checkbox>
        )}
      </Space>
    </Modal>
  );
}

/** One job's progress and results, live from the user's own channel. */
export function BulkProgress({ jobId, onClose }: { jobId: string | null; onClose: () => void }) {
  const t = useLabel();
  const dates = useDateTime();
  const job = useBulkJob(jobId ?? undefined);
  const data = job.data;
  const skipped = (data?.results ?? []).filter((r) => r.outcome === 'skipped');
  const running = data?.status === 'queued' || data?.status === 'running';
  return (
    <Drawer
      open={jobId !== null}
      onClose={onClose}
      width={520}
      title={data ? t(`incidents.bulk.title.${data.action}`, { count: data.total }) : ''}
      data-testid="inc-bulk-progress"
    >
      {data !== undefined && (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Progress
            percent={data.total === 0 ? 100 : Math.round((data.processed / data.total) * 100)}
            status={data.status === 'failed' ? 'exception' : running ? 'active' : 'success'}
            aria-label={t('incidents.bulk.progress')}
          />
          <Typography.Text data-testid="inc-bulk-status" aria-live="polite">
            {t(`incidents.bulk.status.${data.status}`, {
              processed: data.processed,
              total: data.total,
              done: data.done_count,
              skipped: data.skipped_count,
            })}
          </Typography.Text>
          {data.finished_at !== null && (
            <Typography.Text type="secondary">
              {t('incidents.bulk.finished_at', { at: dates.format(data.finished_at) })}
            </Typography.Text>
          )}
          {skipped.length > 0 && (
            <>
              <Typography.Title level={5}>
                {t('incidents.bulk.skipped_title', { count: skipped.length })}
              </Typography.Title>
              <List
                size="small"
                dataSource={skipped}
                data-testid="inc-bulk-skipped"
                renderItem={(result) => (
                  <List.Item data-testid={`inc-bulk-skipped-${result.display_id ?? result.id}`}>
                    <Space direction="vertical" size={0}>
                      <Typography.Link href={`/incidents/${result.id}`}>
                        {result.display_id ?? t('incidents.bulk.unknown_record')}
                      </Typography.Link>
                      <Typography.Text type="secondary">{skipReason(t, result)}</Typography.Text>
                    </Space>
                  </List.Item>
                )}
              />
            </>
          )}
        </Space>
      )}
    </Drawer>
  );
}

/** Your recent bulk changes, so a result is findable after leaving the page (AC3). */
export function BulkJobsButton({ onOpen }: { onOpen: (id: string) => void }) {
  const t = useLabel();
  const dates = useDateTime();
  const [open, setOpen] = useState(false);
  const jobs = useBulkJobs(open);
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
        data-testid="inc-bulk-jobs"
      >
        {t('incidents.bulk.recent')}
      </Button>
      <Drawer
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title={t('incidents.bulk.recent')}
        width={460}
      >
        <List
          dataSource={jobs.data ?? []}
          locale={{ emptyText: t('incidents.bulk.none') }}
          renderItem={(job) => (
            <List.Item
              actions={[
                <Button
                  key="open"
                  size="small"
                  onClick={() => {
                    setOpen(false);
                    onOpen(job.id);
                  }}
                >
                  {t('incidents.bulk.details')}
                </Button>,
              ]}
            >
              <Space direction="vertical" size={0}>
                <Typography.Text>
                  {t(`incidents.bulk.title.${job.action}`, { count: job.total })}
                </Typography.Text>
                <Space size={4} wrap>
                  <Tag>{t(`incidents.bulk.state.${job.status}`)}</Tag>
                  <Typography.Text type="secondary">
                    {dates.relative(job.created_at)}
                  </Typography.Text>
                </Space>
              </Space>
            </List.Item>
          )}
        />
      </Drawer>
    </>
  );
}
