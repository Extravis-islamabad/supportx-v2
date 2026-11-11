import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Card,
  Checkbox,
  DatePicker,
  Flex,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Typography,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  queryKeys,
  useAssetLoans,
  useLoanableAssets,
  useLoanActions,
  useUser,
  type AssetLoan,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  CellText,
  EmptyText,
  FilterBar,
  lengthLimit,
  ListPage,
  NoAccess,
  PageHeader,
  pickerFormat,
  ToneTag,
  useAccess,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
  type Tone,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { DepartmentPicker, SitePicker, UserPicker } from '../incidents/pickers';
import { DepartmentName } from './AssetRelations';
import { useSiteNames } from './live';
import { okFooter } from './dialogOk';
import { problemText } from './problemText';

const STATUS_TONE: Record<AssetLoan['status'], Tone> = {
  open: 'info',
  overdue: 'error',
  closed: 'default',
};
const COMMENT_MAX = 2000;

// The register's status filter (REQ-AST-030): every loan still out, or one status.
type StatusFilter = 'out' | AssetLoan['status'];
const STATUS_FILTERS: StatusFilter[] = ['out', 'open', 'overdue', 'closed'];

/** Who has it: the person, and the department it is lent to when there is one. */
function Borrower({ loan }: { loan: AssetLoan }) {
  const t = useLabel();
  const user = useUser(loan.borrower_id);
  const person = user.data?.display_name ?? t('audit.ui.erased_person');
  if (loan.department_id == null) return <CellText>{person}</CellText>;
  return (
    <Space direction="vertical" size={0}>
      <DepartmentName id={loan.department_id} />
      <Typography.Text type="secondary">
        {t('assets.loans.collected_by', { name: person })}
      </Typography.Text>
    </Space>
  );
}

function assetText(a: { tag: string | null; name: string }): string {
  return `${a.tag ?? ''} ${a.name}`.trim();
}

/** A new loan: who, which loanable assets, until when (REQ-AST-030). */
function NewLoanDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const { dates } = useAppearance();
  const { createLoan } = useLoanActions();
  const [borrower, setBorrower] = useState<string | null>(null);
  const [department, setDepartment] = useState<string | null>(null);
  const [site, setSite] = useState<string | null>(null);
  const [assets, setAssets] = useState<string[]>([]);
  const [due, setDue] = useState<Dayjs | null>(() => dayjs().add(7, 'day').endOf('day'));
  const [comment, setComment] = useState('');
  const [search, setSearch] = useState('');
  const searched = useDebounced(search, 250);
  const offered = useLoanableAssets(searched, open);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<string | null>(null);
  const close = () => {
    setBorrower(null);
    setDepartment(null);
    setSite(null);
    setAssets([]);
    setComment('');
    setProblem(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  const ready = borrower !== null && assets.length > 0 && due !== null;
  return (
    <Modal
      open={open}
      title={t('assets.loans.new')}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('assets.loans.give'),
        loading: createLoan.isPending,
        whyDisabled:
          borrower === null
            ? t('assets.loans.borrower_needed')
            : assets.length === 0
              ? t('assets.loans.assets_needed')
              : due === null
                ? t('assets.loans.due_needed')
                : undefined,
        onOk: () => {
          if (!ready) return;
          setProblem(null);
          createLoan.mutate(
            {
              key,
              borrowerId: borrower,
              assetIds: assets,
              dueAt: due.toISOString(),
              comment: comment.trim() || undefined,
              departmentId: department,
              siteId: site,
            },
            {
              onSuccess: close,
              onError: (error) => {
                setProblem(problemText(t, error));
              },
            },
          );
        },
      })}
      destroyOnHidden
      data-testid="asset-loan-new"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.loans.borrower')} required>
          <UserPicker
            value={borrower}
            onChange={setBorrower}
            testId="asset-loan-borrower"
            ariaLabel={t('assets.loans.borrower')}
          />
        </Form.Item>
        <Form.Item label={t('assets.loans.department')} extra={t('assets.loans.department_help')}>
          <DepartmentPicker
            value={department}
            onChange={setDepartment}
            testId="asset-loan-department"
            ariaLabel={t('assets.loans.department')}
          />
        </Form.Item>
        <Form.Item label={t('assets.loans.site')}>
          <SitePicker
            value={site}
            onChange={setSite}
            testId="asset-loan-site"
            ariaLabel={t('assets.loans.site')}
          />
        </Form.Item>
        <Form.Item label={t('assets.loans.assets')} required extra={t('assets.loans.assets_help')}>
          <Select
            mode="multiple"
            showSearch
            filterOption={false}
            value={assets}
            onSearch={setSearch}
            onChange={setAssets}
            loading={offered.isFetching}
            aria-label={t('assets.loans.assets')}
            notFoundContent={<EmptyText>{t('assets.loans.none_loanable')}</EmptyText>}
            options={(offered.data ?? []).map((a) => ({ value: a.id, label: assetText(a) }))}
            data-testid="asset-loan-assets"
          />
        </Form.Item>
        <Form.Item label={t('assets.loans.due')} required>
          <DatePicker
            showTime={{ format: dates.timeFormat === '12h' ? 'hh:mm A' : 'HH:mm' }}
            format={pickerFormat(dates, true)}
            value={due}
            onChange={setDue}
            disabledDate={(day) => day.isBefore(dayjs(), 'day')}
            aria-label={t('assets.loans.due')}
            data-testid="asset-loan-due"
          />
        </Form.Item>
        <Form.Item label={t('assets.loans.comment')}>
          <Input.TextArea
            aria-label={t('assets.loans.comment')}
            value={comment}
            count={lengthLimit(COMMENT_MAX)}
            autoSize={{ minRows: 2, maxRows: 5 }}
            onChange={(event) => {
              setComment(event.target.value);
            }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** Take some or all of a loan's assets back, to stock or to repair (REQ-AST-031). */
function ReturnDialog({ loan, onClose }: { loan: AssetLoan | undefined; onClose: () => void }) {
  const t = useLabel();
  const { returnItems } = useLoanActions();
  const out = (loan?.assets ?? []).filter((a) => a.returned_at === null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [outcome, setOutcome] = useState<'in_stock' | 'in_repair'>('in_stock');
  const [comment, setComment] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const chosen = picked ?? out.map((a) => a.id);
  const close = () => {
    setPicked(null);
    setOutcome('in_stock');
    setComment('');
    setProblem(null);
    onClose();
  };
  const needsReason = outcome === 'in_repair' && comment.trim() === '';
  return (
    <Modal
      open={loan !== undefined}
      title={t('assets.loans.return_title')}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('assets.loans.take_back'),
        loading: returnItems.isPending,
        whyDisabled:
          chosen.length === 0
            ? t('assets.loans.pick_needed')
            : needsReason
              ? t('assets.loans.repair_help')
              : undefined,
        onOk: () => {
          if (loan === undefined) return;
          setProblem(null);
          returnItems.mutate(
            {
              loanId: loan.id,
              assetIds: chosen,
              outcome,
              comment: comment.trim() || undefined,
            },
            {
              onSuccess: close,
              onError: (error) => {
                setProblem(problemText(t, error));
              },
            },
          );
        },
      })}
      destroyOnHidden
      data-testid="asset-loan-return"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.loans.coming_back')}>
          <Checkbox.Group
            value={chosen}
            onChange={(values) => {
              setPicked(values);
            }}
            data-testid="asset-loan-return-assets"
          >
            <Flex vertical gap={4}>
              {out.map((a) => (
                <Checkbox key={a.id} value={a.id}>
                  <bdi dir="auto">{assetText(a)}</bdi>
                </Checkbox>
              ))}
            </Flex>
          </Checkbox.Group>
        </Form.Item>
        <Form.Item label={t('assets.loans.outcome')}>
          <Segmented<'in_stock' | 'in_repair'>
            value={outcome}
            onChange={setOutcome}
            options={(['in_stock', 'in_repair'] as const).map((o) => ({
              value: o,
              label: t(`asset_loan_outcome.${o}`),
            }))}
            data-testid="asset-loan-return-outcome"
          />
        </Form.Item>
        <Form.Item
          label={t('assets.loans.comment')}
          required={outcome === 'in_repair'}
          extra={outcome === 'in_repair' ? t('assets.loans.repair_help') : undefined}
        >
          <Input.TextArea
            aria-label={t('assets.loans.comment')}
            value={comment}
            count={lengthLimit(COMMENT_MAX)}
            autoSize={{ minRows: 2, maxRows: 5 }}
            onChange={(event) => {
              setComment(event.target.value);
            }}
            data-testid="asset-loan-return-comment"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/**
 * The loan register (WP-049a s5; REQ-AST-030, 031): every open loan, overdue first, with what is
 * still out. New loans and returns here; live from the loan events (rule c). Built from the
 * shared page parts only, so it moves onto the UI pass 3 list template as it is (D-147).
 */
export function LoansPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const access = useAccess();
  const dates = useDateTime();
  const queryClient = useQueryClient();
  const allowed = access.can('assets.view');
  const manage = access.can('assets.manage');
  const [status, setStatus] = useState<StatusFilter>('out');
  const [siteFilter, setSiteFilter] = useState<string | null>(null);
  const siteName = useSiteNames();
  const loans = useAssetLoans(
    { status: status === 'out' ? undefined : status, siteId: siteFilter ?? undefined },
    allowed,
  );
  const [adding, setAdding] = useState(false);
  const [returning, setReturning] = useState<string>();
  useTenantChannel((event) => {
    if (event.type === 'assets.loans_changed')
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.loans });
  });
  if (!allowed) return <NoAccess titleKey="nav.assets" />;
  const rows = loans.data ?? [];
  return (
    <ListPage
      testId="asset-loans-page"
      header={
        <PageHeader
          title={t('assets.loans.title')}
          back={{ label: t('nav.assets'), onClick: () => void navigate('/assets') }}
          count={loans.data === undefined ? undefined : String(rows.length)}
          extra={
            manage && (
              <WriteButton
                type="primary"
                onClick={() => {
                  setAdding(true);
                }}
                data-testid="asset-loan-new-open"
              >
                {t('assets.loans.new')}
              </WriteButton>
            )
          }
        />
      }
      filters={
        <FilterBar
          testId="asset-loans-filterbar"
          view={
            <Segmented<StatusFilter>
              value={status}
              onChange={setStatus}
              options={STATUS_FILTERS.map((s) => ({
                value: s,
                label: s === 'out' ? t('assets.loans.all_out') : t(`asset_loan_status.${s}`),
              }))}
              data-testid="asset-loans-status"
            />
          }
          quick={
            <div style={{ minWidth: 200 }}>
              <SitePicker
                value={siteFilter}
                onChange={setSiteFilter}
                ariaLabel={t('assets.loans.site')}
                testId="asset-loans-site"
              />
            </div>
          }
        />
      }
    >
      <Card>
        <Table<AssetLoan>
          size="small"
          rowKey="id"
          loading={loans.isPending}
          dataSource={rows}
          pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: <EmptyText>{t('assets.loans.none')}</EmptyText> }}
          data-testid="asset-loans"
          columns={[
            {
              key: 'id',
              title: t('assets.loans.display_id'),
              render: (_, loan) => (
                <span style={{ whiteSpace: 'nowrap' }} data-testid={`asset-loan-id-${loan.id}`}>
                  {loan.display_id == null ? '' : <bdi dir="ltr">{loan.display_id}</bdi>}
                </span>
              ),
            },
            {
              key: 'borrower',
              title: t('assets.loans.borrower'),
              render: (_, loan) => <Borrower loan={loan} />,
            },
            {
              key: 'site',
              title: t('assets.loans.site'),
              render: (_, loan) => (
                <CellText>
                  {loan.site_id == null ? '' : <bdi dir="auto">{siteName(loan.site_id)}</bdi>}
                </CellText>
              ),
            },
            {
              key: 'assets',
              title: t('assets.loans.assets'),
              render: (_, loan) => (
                <Space direction="vertical" size={0}>
                  {loan.assets.map((a) => (
                    <Typography.Text
                      key={a.id}
                      type={a.returned_at === null ? undefined : 'secondary'}
                    >
                      <Link to={`/assets/${a.id}`}>
                        <bdi dir="auto">{assetText(a)}</bdi>
                      </Link>
                      {a.returned_at !== null &&
                        ` · ${t(`asset_loan_outcome.${a.outcome ?? 'in_stock'}`)}`}
                    </Typography.Text>
                  ))}
                </Space>
              ),
            },
            {
              key: 'starts',
              title: t('assets.loans.starts'),
              render: (_, loan) => (
                <span style={{ whiteSpace: 'nowrap' }}>{dates.format(loan.starts_at)}</span>
              ),
            },
            {
              key: 'due',
              title: t('assets.loans.due'),
              render: (_, loan) => (
                <span style={{ whiteSpace: 'nowrap' }}>{dates.format(loan.due_at)}</span>
              ),
            },
            {
              key: 'status',
              title: t('assets.loans.status'),
              render: (_, loan) => (
                <ToneTag tone={STATUS_TONE[loan.status]} testId={`asset-loan-status-${loan.id}`}>
                  {t(`asset_loan_status.${loan.status}`)}
                </ToneTag>
              ),
            },
            ...(manage
              ? [
                  {
                    key: 'actions',
                    title: t('assets.loans.actions'),
                    // Always in view when the table scrolls sideways (390 px), as on the
                    // incident list; antd mirrors it in right-to-left.
                    fixed: 'right' as const,
                    render: (_: unknown, loan: AssetLoan) =>
                      loan.status === 'closed' ? null : (
                        <WriteButton
                          size="small"
                          onClick={() => {
                            setReturning(loan.id);
                          }}
                          data-testid={`asset-loan-return-open-${loan.id}`}
                        >
                          {t('assets.loans.take_back')}
                        </WriteButton>
                      ),
                  },
                ]
              : []),
          ]}
        />
      </Card>
      <NewLoanDialog
        open={adding}
        onClose={() => {
          setAdding(false);
        }}
      />
      <ReturnDialog
        loan={rows.find((l) => l.id === returning)}
        onClose={() => {
          setReturning(undefined);
        }}
      />
    </ListPage>
  );
}
