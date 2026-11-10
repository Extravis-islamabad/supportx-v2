import { Alert, Button, Card, DatePicker, Flex, Form, Input, Modal, Popconfirm, Table } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useState } from 'react';

import {
  useAssetBookings,
  useBookingActions,
  useUser,
  type AssetBooking,
  type AssetRecord,
} from '@supportx/api-client';
import {
  CellText,
  lengthLimit,
  loadedEmpty,
  pickerFormat,
  ToneTag,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
  type Tone,
} from '@supportx/ui';

import { DepartmentPicker, UserPicker } from '../incidents/pickers';
import { DepartmentName } from './AssetRelations';
import { okFooter } from './dialogOk';
import { nextFree, useBookingsLive } from './live';
import { problemText } from './problemText';

const COMMENT_MAX = 2000;
const STATUS_TONE: Record<AssetBooking['status'], Tone> = {
  booked: 'info',
  handed_over: 'success',
  cancelled: 'default',
};

function Person({ id }: { id: string }) {
  const t = useLabel();
  const user = useUser(id);
  return <bdi dir="auto">{user.data?.display_name ?? t('audit.ui.erased_person')}</bdi>;
}

/**
 * Book this asset for a period (REQ-AST-032). A taken period is refused with the next free day,
 * which one click takes (the same length of time).
 */
function BookDialog({
  asset,
  open,
  onClose,
}: {
  asset: AssetRecord;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { dates } = useAppearance();
  const formatter = useDateTime();
  const { book } = useBookingActions();
  const [borrower, setBorrower] = useState<string | null>(null);
  const [department, setDepartment] = useState<string | null>(null);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(() => {
    const start = dayjs().add(1, 'day').hour(9).minute(0).second(0).millisecond(0);
    return [start, start.hour(17)];
  });
  const [comment, setComment] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<string | null>(null);
  const [suggested, setSuggested] = useState<string | null>(null);
  const close = () => {
    setBorrower(null);
    setDepartment(null);
    setComment('');
    setProblem(null);
    setSuggested(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  const showTime = { format: dates.timeFormat === '12h' ? 'hh:mm A' : 'HH:mm' };
  return (
    <Modal
      open={open}
      title={t('assets.bookings.new')}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: t('assets.bookings.book'),
        loading: book.isPending,
        testId: 'asset-booking-save',
        whyDisabled:
          borrower === null
            ? t('assets.bookings.borrower_needed')
            : range === null
              ? t('assets.bookings.dates_needed')
              : undefined,
        onOk: () => {
          if (borrower === null || range === null) return;
          setProblem(null);
          setSuggested(null);
          book.mutate(
            {
              key,
              body: {
                asset_id: asset.id,
                borrower_id: borrower,
                department_id: department,
                starts_at: range[0].toISOString(),
                ends_at: range[1].toISOString(),
                comment: comment.trim() || null,
              },
            },
            {
              onSuccess: close,
              onError: (error) => {
                const free = nextFree(error);
                setSuggested(free);
                setKey(crypto.randomUUID()); // a retry is a new booking
                setProblem(
                  problemText(t, error, (code, given) =>
                    code === 'asset_booking_taken'
                      ? { ...given, next_free: free === null ? '' : formatter.format(free) }
                      : given,
                  ),
                );
              },
            },
          );
        },
      })}
      destroyOnHidden
      data-testid="asset-booking-new"
    >
      {problem !== null && (
        <Alert
          type="error"
          showIcon
          message={problem}
          style={{ marginBottom: 12 }}
          data-testid="asset-booking-problem"
          action={
            suggested !== null && range !== null ? (
              <Button
                size="small"
                onClick={() => {
                  const start = dayjs(suggested);
                  setRange([start, start.add(range[1].diff(range[0]), 'millisecond')]);
                  setProblem(null);
                  setSuggested(null);
                }}
                data-testid="asset-booking-take-suggestion"
              >
                {t('assets.bookings.take_suggestion')}
              </Button>
            ) : undefined
          }
        />
      )}
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.bookings.borrower')} required>
          <UserPicker
            value={borrower}
            onChange={setBorrower}
            testId="asset-booking-borrower"
            ariaLabel={t('assets.bookings.borrower')}
          />
        </Form.Item>
        <Form.Item label={t('assets.bookings.department')}>
          <DepartmentPicker
            value={department}
            onChange={setDepartment}
            testId="asset-booking-department"
            ariaLabel={t('assets.bookings.department')}
          />
        </Form.Item>
        <Form.Item label={t('assets.bookings.when')} required>
          <DatePicker.RangePicker
            showTime={showTime}
            format={pickerFormat(dates, true)}
            value={range}
            onChange={(next) => {
              const [start, end] = next ?? [];
              setRange(start != null && end != null ? [start, end] : null);
            }}
            disabledDate={(day) => day.isBefore(dayjs(), 'day')}
            aria-label={t('assets.bookings.when')}
            data-testid="asset-booking-when"
          />
        </Form.Item>
        <Form.Item label={t('assets.bookings.comment')}>
          <Input.TextArea
            aria-label={t('assets.bookings.comment')}
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

/**
 * The asset's bookings ahead (WP-049b s1; REQ-AST-032): book it, cancel, and hand it over, which
 * turns the booking into a loan with the same dates (AC2). Live from `assets.bookings_changed`.
 */
export function AssetBookings({ asset, manage }: { asset: AssetRecord; manage: boolean }) {
  const t = useLabel();
  const dates = useDateTime();
  const bookings = useAssetBookings({ assetId: asset.id });
  const { cancel, handOver } = useBookingActions();
  const [adding, setAdding] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  useBookingsLive();
  const failed = (error: unknown) => {
    setProblem(problemText(t, error));
  };
  const rows = bookings.data ?? [];
  return (
    <Card
      title={t('assets.bookings.title')}
      extra={
        manage && (
          <WriteButton
            size="small"
            disabled={!asset.loanable}
            whyDisabled={t('assets.bookings.loanable_needed')}
            onClick={() => {
              setAdding(true);
            }}
            data-testid="asset-booking-new-open"
          >
            {t('assets.bookings.new')}
          </WriteButton>
        )
      }
      data-testid="asset-bookings"
    >
      {problem !== null && (
        <Alert
          type="error"
          showIcon
          closable
          message={problem}
          onClose={() => {
            setProblem(null);
          }}
          style={{ marginBottom: 12 }}
        />
      )}
      <Table<AssetBooking>
        size="small"
        rowKey="id"
        loading={bookings.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: loadedEmpty(bookings.isPending, t('assets.bookings.none')) }}
        columns={[
          {
            key: 'when',
            title: t('assets.bookings.when'),
            render: (_, b) => (
              <span style={{ whiteSpace: 'nowrap' }}>
                {dates.format(b.starts_at)}
                {' – '}
                {dates.format(b.ends_at)}
              </span>
            ),
          },
          {
            key: 'borrower',
            title: t('assets.bookings.borrower'),
            render: (_, b) => (
              <Flex vertical gap={0}>
                <Person id={b.borrower_id} />
                {b.department_id !== null && <DepartmentName id={b.department_id} />}
              </Flex>
            ),
          },
          {
            key: 'status',
            title: t('assets.bookings.status'),
            render: (_, b) => (
              <Flex gap={4} wrap>
                <ToneTag tone={STATUS_TONE[b.status]} testId={`asset-booking-status-${b.id}`}>
                  {t(`asset_booking_status.${b.status}`)}
                </ToneTag>
                {b.channel === 'portal' && (
                  <ToneTag tone="default">{t('asset_booking_channel.portal')}</ToneTag>
                )}
              </Flex>
            ),
          },
          {
            key: 'comment',
            title: t('assets.bookings.comment'),
            render: (_, b) => (
              <CellText title={b.comment ?? undefined}>
                {b.comment === null ? '' : <bdi dir="auto">{b.comment}</bdi>}
              </CellText>
            ),
          },
          ...(manage
            ? [
                {
                  key: 'actions',
                  title: t('assets.loans.actions'),
                  fixed: 'right' as const,
                  render: (_: unknown, b: AssetBooking) =>
                    b.status !== 'booked' ? null : (
                      <Flex gap={4}>
                        <Popconfirm
                          title={t('assets.bookings.hand_over_confirm')}
                          okText={t('assets.bookings.hand_over')}
                          cancelText={t('actions.cancel')}
                          onConfirm={() => {
                            setProblem(null);
                            handOver.mutate({ id: b.id, version: b.version }, { onError: failed });
                          }}
                        >
                          <WriteButton size="small" data-testid={`asset-booking-handover-${b.id}`}>
                            {t('assets.bookings.hand_over')}
                          </WriteButton>
                        </Popconfirm>
                        <Popconfirm
                          title={t('assets.bookings.cancel_confirm')}
                          okText={t('assets.bookings.cancel')}
                          cancelText={t('actions.cancel')}
                          onConfirm={() => {
                            setProblem(null);
                            cancel.mutate({ id: b.id, version: b.version }, { onError: failed });
                          }}
                        >
                          <WriteButton
                            size="small"
                            danger
                            data-testid={`asset-booking-cancel-${b.id}`}
                          >
                            {t('assets.bookings.cancel')}
                          </WriteButton>
                        </Popconfirm>
                      </Flex>
                    ),
                },
              ]
            : []),
        ]}
        data-testid="asset-bookings-table"
      />
      <BookDialog
        asset={asset}
        open={adding}
        onClose={() => {
          setAdding(false);
        }}
      />
    </Card>
  );
}
