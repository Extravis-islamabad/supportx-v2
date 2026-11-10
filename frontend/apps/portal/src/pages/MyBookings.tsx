import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Form,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Typography,
} from 'antd';
import { useState, type ComponentProps } from 'react';

import {
  ApiError,
  queryKeys,
  useBookableAssets,
  useMyBookingActions,
  useMyBookings,
} from '@supportx/api-client';
import { usePersonalChannel, useTenantChannel } from '@supportx/realtime';
import {
  loadedEmpty,
  EmptyText,
  pickerFormat,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { useDebounced } from '../useDebounced';

// antd's own date type (the portal does not import dayjs itself).
type Day = Parameters<NonNullable<ComponentProps<typeof DatePicker>['disabledDate']>>[0];

const MINE_CHANGED = 'assets.mine_changed';
const BOOKINGS_CHANGED = 'assets.bookings_changed';

/** A refusal as words (never a code); a taken period names the next free day. */
function problemOf(
  t: ReturnType<typeof useLabel>,
  format: (iso: string) => string,
  error: unknown,
): string | null {
  if (error instanceof ApiError && error.problem !== null) {
    const field = error.fieldErrors[0];
    if (field !== undefined) return t(`errors.field.${field.code}`, field.params ?? {});
    const free = error.params.next_free;
    return t(
      error.messageKey,
      typeof free === 'string' && free !== ''
        ? { ...error.params, next_free: format(free) }
        : error.params,
    );
  }
  reportError(error);
  return null;
}

function BookDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const { dates } = useAppearance();
  const { format } = useDateTime();
  const { book } = useMyBookingActions();
  const [search, setSearch] = useState('');
  const searched = useDebounced(search, 250);
  const offered = useBookableAssets(searched, open);
  const [asset, setAsset] = useState<string | null>(null);
  const [range, setRange] = useState<[Day, Day] | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<string | null>(null);
  const close = () => {
    setAsset(null);
    setRange(null);
    setProblem(null);
    setKey(crypto.randomUUID());
    onClose();
  };
  // A grey button never stays silent (D-155): the dialog says what is still missing.
  const whyDisabled =
    asset === null
      ? t('my_assets.book_asset_needed')
      : range === null
        ? t('my_assets.book_dates_needed')
        : undefined;
  return (
    <Modal
      open={open}
      title={t('my_assets.book_title')}
      okText={t('my_assets.book')}
      cancelText={t('actions.cancel')}
      okButtonProps={{
        disabled: whyDisabled !== undefined,
        'aria-describedby': whyDisabled === undefined ? undefined : 'my-booking-why',
      }}
      confirmLoading={book.isPending}
      onCancel={close}
      onOk={() => {
        if (asset === null || range === null) return;
        setProblem(null);
        book.mutate(
          {
            key,
            body: {
              asset_id: asset,
              starts_at: range[0].toISOString(),
              ends_at: range[1].toISOString(),
            },
          },
          {
            onSuccess: close,
            onError: (error) => {
              setKey(crypto.randomUUID());
              setProblem(problemOf(t, format, error));
            },
          },
        );
      }}
      destroyOnHidden
      data-testid="my-booking-new"
    >
      {problem !== null && (
        <Alert
          type="error"
          showIcon
          message={problem}
          style={{ marginBottom: 12 }}
          data-testid="my-booking-problem"
        />
      )}
      <Form layout="vertical" component="div">
        <Form.Item label={t('my_assets.book_what')} required>
          <Select
            showSearch
            filterOption={false}
            value={asset}
            onSearch={setSearch}
            onChange={setAsset}
            loading={offered.isFetching}
            aria-label={t('my_assets.book_what')}
            notFoundContent={<EmptyText>{t('my_assets.none_bookable')}</EmptyText>}
            options={(offered.data ?? []).map((a) => ({
              value: a.id,
              label: `${a.tag ?? ''} ${a.name}`.trim(),
            }))}
            data-testid="my-booking-asset"
          />
        </Form.Item>
        <Form.Item label={t('my_assets.book_when')} required>
          <DatePicker.RangePicker
            showTime={{ format: dates.timeFormat === '12h' ? 'hh:mm A' : 'HH:mm' }}
            format={pickerFormat(dates, true)}
            value={range}
            onChange={(next) => {
              const [start, end] = next ?? [];
              setRange(start != null && end != null ? [start, end] : null);
            }}
            disabledDate={(day) => day.endOf('day').valueOf() < Date.now()}
            aria-label={t('my_assets.book_when')}
            data-testid="my-booking-when"
          />
        </Form.Item>
      </Form>
      {whyDisabled !== undefined && (
        <Typography.Text type="secondary" id="my-booking-why" data-testid="my-booking-why">
          {whyDisabled}
        </Typography.Text>
      )}
    </Modal>
  );
}

/**
 * My bookings ahead in the portal (WP-049b s1; REQ-AST-032 AC3): shown only while the
 * organisation allows booking here. Live: the booker's own channel and the tenant's bookings.
 */
export function MyBookings() {
  const t = useLabel();
  const { format } = useDateTime();
  const queryClient = useQueryClient();
  const mine = useMyBookings();
  const { cancel } = useMyBookingActions();
  const [booking, setBooking] = useState(false);
  const refresh = (type: string) => {
    if (type === MINE_CHANGED || type === BOOKINGS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.myBookings });
    }
  };
  usePersonalChannel((event) => {
    refresh(event.type);
  });
  useTenantChannel((event) => {
    refresh(event.type);
  });
  const data = mine.data;
  if (data?.enabled !== true) return null;
  return (
    <Card
      title={t('my_assets.bookings')}
      extra={
        <Button
          type="primary"
          onClick={() => {
            setBooking(true);
          }}
          data-testid="my-booking-new-open"
        >
          {t('my_assets.book')}
        </Button>
      }
      data-testid="my-bookings"
    >
      <List
        dataSource={data.bookings}
        locale={{ emptyText: loadedEmpty(mine.isPending, t('my_assets.no_bookings')) }}
        renderItem={(b) => (
          <List.Item
            key={b.id}
            data-testid={`my-booking-${b.id}`}
            actions={[
              <Popconfirm
                key="cancel"
                title={t('my_assets.cancel_booking_confirm')}
                okText={t('my_assets.cancel_booking_yes')}
                cancelText={t('my_assets.keep_booking')}
                onConfirm={() => {
                  cancel.mutate({ id: b.id, version: b.version }, { onError: reportError });
                }}
              >
                <Button size="small" danger data-testid={`my-booking-cancel-${b.id}`}>
                  {t('my_assets.cancel_booking')}
                </Button>
              </Popconfirm>,
            ]}
          >
            <List.Item.Meta
              title={<bdi dir="auto">{data.assets[b.asset_id] ?? ''}</bdi>}
              description={
                <Space wrap>
                  {format(b.starts_at)}
                  {'–'}
                  {format(b.ends_at)}
                </Space>
              }
            />
          </List.Item>
        )}
      />
      <BookDialog
        open={booking}
        onClose={() => {
          setBooking(false);
        }}
      />
    </Card>
  );
}
