import { Alert, Form, Input, InputNumber, List, Modal, Select, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import {
  ApiError,
  useAssetActions,
  useAssetMoves,
  useAssetSettings,
  useAssetStates,
  type AssetBulkMoveResult,
  type AssetRecord,
} from '@supportx/api-client';
import { lengthLimit, reportError, useAppearance, useLabel } from '@supportx/ui';

import { nameOf } from '../admin/assets/shared';
import { okFooter } from './dialogOk';

const REASON_MAX = 500;

function newKey(): string {
  return crypto.randomUUID();
}

/** The problem's own message when the server names one, else the general report. */
function problemText(t: ReturnType<typeof useLabel>, error: unknown): string | null {
  if (error instanceof ApiError && error.problem !== null) {
    return t(error.messageKey, error.params);
  }
  reportError(error);
  return null;
}

/**
 * Move one asset along its life cycle (REQ-AST-012, 013): only the moves its life cycle lists
 * from its state now; moves you may not make are shown, disabled, with why. A move or state
 * that asks for a reason asks for it here.
 */
export function MoveAssetDialog({
  asset,
  open,
  onClose,
}: {
  asset: AssetRecord;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const states = useAssetStates(open);
  const moves = useAssetMoves(open ? asset.id : undefined);
  const { move } = useAssetActions();
  const [target, setTarget] = useState<string>();
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  const stateName = (id: string) => {
    const found = states.data?.find((s) => s.id === id);
    return found === undefined ? '' : nameOf(found.names, locale);
  };
  const chosen = moves.data?.find((m) => m.to_state_id === target);
  const needsReason = chosen?.reason_required === true;
  const reasonMissing = needsReason && reason.trim() === '';
  const close = () => {
    setTarget(undefined);
    setReason('');
    setProblem(null);
    setTried(false);
    onClose();
  };
  const submit = () => {
    setTried(true);
    if (target === undefined || reasonMissing) return;
    setProblem(null);
    move.mutate(
      {
        id: asset.id,
        version: asset.version,
        toStateId: target,
        reason: reason.trim() === '' ? undefined : reason.trim(),
      },
      {
        onSuccess: close,
        onError: (error) => {
          setProblem(problemText(t, error));
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      title={t('assets.move.title', { name: asset.name })}
      okText={t('assets.move.ok')}
      cancelText={t('actions.cancel')}
      onOk={submit}
      onCancel={close}
      confirmLoading={move.isPending}
      destroyOnHidden
      data-testid="asset-move-dialog"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      {moves.data?.length === 0 ? (
        <Typography.Text type="secondary">{t('assets.move.none')}</Typography.Text>
      ) : (
        <Form layout="vertical" component="div">
          <Form.Item
            label={t('assets.move.to')}
            required
            validateStatus={tried && target === undefined ? 'error' : undefined}
            help={tried && target === undefined ? t('assets.move.pick') : undefined}
          >
            <Select
              value={target}
              onChange={setTarget}
              loading={moves.isPending}
              data-testid="asset-move-to"
              options={(moves.data ?? []).map((m) => ({
                value: m.to_state_id,
                disabled: !m.allowed,
                label: m.allowed
                  ? stateName(m.to_state_id)
                  : t('assets.move.not_yours', { state: stateName(m.to_state_id) }),
              }))}
            />
          </Form.Item>
          <Form.Item
            label={t('assets.move.reason')}
            required={needsReason}
            validateStatus={tried && reasonMissing ? 'error' : undefined}
            help={tried && reasonMissing ? t('assets.move.reason_needed') : undefined}
          >
            <Input.TextArea
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
              }}
              rows={3}
              count={lengthLimit(REASON_MAX)}
              data-testid="asset-move-reason"
            />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}

/**
 * Copy an asset (REQ-AST-010): up to the tenant's copy limit; each copy gets its own tag and
 * starts in stock, without the serial, barcode or discovered details. One copy opens it.
 */
export function CopyAssetDialog({
  asset,
  open,
  onClose,
}: {
  asset: AssetRecord;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const settings = useAssetSettings(open);
  const { copy } = useAssetActions();
  const limit = settings.data?.copy_limit ?? 50;
  const [count, setCount] = useState<number | null>(1);
  const [key, setKey] = useState(newKey);
  const [problem, setProblem] = useState<string | null>(null);
  const close = () => {
    setCount(1);
    setKey(newKey());
    setProblem(null);
    onClose();
  };
  const submit = () => {
    if (count === null || count < 1 || count > limit) return;
    setProblem(null);
    copy.mutate(
      { id: asset.id, count, key },
      {
        onSuccess: (made) => {
          close();
          const first = made.items[0];
          if (made.items.length === 1 && first !== undefined) void navigate(`/assets/${first.id}`);
        },
        onError: (error) => {
          setProblem(problemText(t, error));
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      title={t('assets.copy.title', { name: asset.name })}
      okText={t('assets.copy.ok', { count: count ?? 0 })}
      cancelText={t('actions.cancel')}
      onOk={submit}
      onCancel={close}
      confirmLoading={copy.isPending}
      destroyOnHidden
      data-testid="asset-copy-dialog"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      <Typography.Paragraph type="secondary">{t('assets.copy.help')}</Typography.Paragraph>
      <Form layout="vertical" component="div">
        <Form.Item label={t('assets.copy.count')} help={t('assets.copy.limit', { max: limit })}>
          <InputNumber
            min={1}
            max={limit}
            precision={0}
            value={count}
            onChange={setCount}
            data-testid="asset-copy-count"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/**
 * Move the selected assets to one state (bulk). Each goes through the single move, so its life
 * cycle, reason and permission still hold; the answer lists the ones that didn't move, and why.
 */
export function BulkMoveDialog({
  assets,
  open,
  onClose,
}: {
  assets: AssetRecord[];
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const states = useAssetStates(open);
  const { bulkMove } = useAssetActions();
  const [target, setTarget] = useState<string>();
  const [reason, setReason] = useState('');
  const [results, setResults] = useState<AssetBulkMoveResult[]>();
  const [problem, setProblem] = useState<string | null>(null);
  const names = useMemo(() => new Map(assets.map((a) => [a.id, a.name])), [assets]);
  const close = () => {
    setTarget(undefined);
    setReason('');
    setResults(undefined);
    setProblem(null);
    onClose();
  };
  const submit = () => {
    if (results !== undefined) {
      close();
      return;
    }
    if (target === undefined) return;
    setProblem(null);
    bulkMove.mutate(
      {
        items: assets.map((a) => ({ asset_id: a.id, version: a.version })),
        toStateId: target,
        reason: reason.trim() === '' ? undefined : reason.trim(),
      },
      {
        onSuccess: (answer) => {
          if (answer.every((r) => r.moved)) close();
          else setResults(answer);
        },
        onError: (error) => {
          setProblem(problemText(t, error));
        },
      },
    );
  };
  const refused = (results ?? []).filter((r) => !r.moved);
  return (
    <Modal
      open={open}
      title={t('assets.bulk_move.title', { count: assets.length })}
      cancelText={t('actions.cancel')}
      onCancel={close}
      footer={okFooter({
        okText: results === undefined ? t('assets.move.ok') : t('actions.close'),
        onOk: submit,
        loading: bulkMove.isPending,
        cancel: results === undefined,
        whyDisabled:
          results === undefined && target === undefined ? t('assets.move.pick') : undefined,
      })}
      destroyOnHidden
      data-testid="asset-bulk-move-dialog"
    >
      {problem !== null && (
        <Alert type="error" showIcon message={problem} style={{ marginBottom: 12 }} />
      )}
      {results === undefined ? (
        <Form layout="vertical" component="div">
          <Form.Item label={t('assets.move.to')} required>
            <Select
              value={target}
              onChange={setTarget}
              data-testid="asset-bulk-move-to"
              options={(states.data ?? []).map((s) => ({
                value: s.id,
                label: nameOf(s.names, locale),
              }))}
            />
          </Form.Item>
          <Form.Item label={t('assets.move.reason')} help={t('assets.bulk_move.reason_help')}>
            <Input.TextArea
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
              }}
              rows={3}
              count={lengthLimit(REASON_MAX)}
              data-testid="asset-bulk-move-reason"
            />
          </Form.Item>
        </Form>
      ) : (
        <>
          <Alert
            type="warning"
            showIcon
            message={t('assets.bulk_move.partial', {
              moved: results.length - refused.length,
              count: refused.length,
            })}
            style={{ marginBottom: 12 }}
            data-testid="asset-bulk-move-partial"
          />
          <List
            size="small"
            dataSource={refused}
            renderItem={(r) => (
              <List.Item key={r.asset_id}>
                <bdi dir="auto">{names.get(r.asset_id) ?? ''}</bdi>
                {': '}
                {t(`errors.${r.code ?? 'bad_request'}`)}
              </List.Item>
            )}
          />
        </>
      )}
    </Modal>
  );
}
