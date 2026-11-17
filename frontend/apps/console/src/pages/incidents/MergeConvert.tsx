import {
  Alert,
  Checkbox,
  Flex,
  Form,
  List,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Typography,
} from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  ApiError,
  useCatalogItem,
  useCatalogItems,
  useConvertPreview,
  useConvertRecord,
  useCustomFields,
  useIncidentTemplates,
  useMergeIncident,
  useMergePreview,
  useMovedLinks,
  useUndoMerge,
  type ConvertibleKind,
  type Incident,
  type IncidentMergePreview,
} from '@supportx/api-client';
import {
  QuestionField,
  reportError,
  requesterQuestions,
  sentAnswers,
  startingAnswers,
  textIn,
  useAppearance,
  useLabel,
  WriteButton,
  type QuestionValue,
} from '@supportx/ui';

import { fieldName } from '../customFields/values';
import { itemName } from '../requests/items';
import { IncidentPicker } from './IncidentPicker';
import { personName, templateLabel } from './labels';
import { UserPicker } from './pickers';

// WP-046b S2 in the console: merging a duplicate into another incident with a preview of what
// moves and who would newly see it (REQ-INC-088), the banner on a merged or converted record
// with undo (REQ-INC-150), and converting an incident and a service request into each other
// (REQ-INC-089). The server decides every right and refusal; these screens say what it says.

const RECORD_PATHS: Record<string, string> = {
  incident: 'incidents',
  service_request: 'requests',
};

/** A preview the server refused, in words (its problem code's label), never empty. */
function Refused({ error, testId }: { error: unknown; testId: string }) {
  const t = useLabel();
  return (
    <Alert
      type="error"
      showIcon
      data-testid={testId}
      message={t(
        error instanceof ApiError ? `errors.${error.code}` : 'errors.unexpected',
        error instanceof ApiError ? error.params : {},
      )}
    />
  );
}

/** The preview's audience lines, counts only: who would newly see the duplicate. */
function Audience({ preview }: { preview: IncidentMergePreview }) {
  const t = useLabel();
  const at = (count: number) =>
    preview.audience_complete ? String(count) : t('incidents.merge.at_least', { count });
  const lines = [
    { key: 'children', count: preview.child_ids.length, text: 'incidents.merge.children_move' },
    { key: 'staff', count: preview.staff_newly_seeing, text: 'incidents.merge.staff_seeing' },
    {
      key: 'requesters',
      count: preview.requesters_newly_seeing,
      text: 'incidents.merge.requesters_seeing',
    },
    {
      key: 'followers',
      count: preview.followers_newly_seeing,
      text: 'incidents.merge.followers_seeing',
    },
    {
      key: 'not_added',
      count: preview.followers_not_added.length,
      text: 'incidents.merge.followers_not_added',
    },
  ].filter((line) => line.count > 0);
  if (lines.length === 0) {
    return (
      <Typography.Text type="secondary" data-testid="inc-merge-nothing-wider">
        {t('incidents.merge.nothing_wider')}
      </Typography.Text>
    );
  }
  return (
    <List
      size="small"
      bordered
      data-testid="inc-merge-preview"
      dataSource={lines}
      renderItem={(line) => (
        <List.Item data-testid={`inc-merge-${line.key}`}>
          {t(line.text, { count: line.count, shown: at(line.count) })}
        </List.Item>
      )}
    />
  );
}

/** Merge this incident into another one: pick, preview, confirm a wider audience, merge. */
export function MergeIncidentDialog({
  item,
  open,
  onClose,
}: {
  item: Incident;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const [into, setInto] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  // The audience grew between the preview and the merge: the new counts are shown, said so.
  const [changed, setChanged] = useState(false);
  const preview = useMergePreview(item.id, open ? into : null);
  const merge = useMergeIncident(item.id);
  const needs = preview.data?.needs_confirmation === true;
  const close = () => {
    setInto(null);
    setConfirmed(false);
    setChanged(false);
    onClose();
  };
  return (
    <Modal
      open={open}
      title={t('incidents.merge.title', { id: item.display_id })}
      onCancel={close}
      destroyOnHidden
      okText={t('incidents.merge.confirm')}
      cancelText={t('actions.cancel')}
      okButtonProps={{
        disabled: into === null || preview.data === undefined || (needs && !confirmed),
        loading: merge.isPending,
        'data-testid': 'inc-merge-confirm',
      }}
      onOk={() => {
        if (into === null) return;
        merge.mutate(
          { intoId: into, confirm: confirmed, version: item.version },
          {
            onSuccess: close,
            onError: (error) => {
              // Someone joined the audience since the preview: show the new counts to confirm.
              if (error instanceof ApiError && error.code === 'merge_widens_audience') {
                setConfirmed(false);
                setChanged(true);
                void preview.refetch();
                return;
              }
              reportError(error);
            },
          },
        );
      }}
    >
      <Flex vertical gap={12} data-testid="inc-merge-dialog">
        <Typography.Paragraph style={{ margin: 0 }}>
          {t('incidents.merge.explain')}
        </Typography.Paragraph>
        <Form layout="vertical" component="div">
          <Form.Item label={t('incidents.merge.into')} htmlFor="inc-merge-into">
            <IncidentPicker
              id="inc-merge-into"
              value={into}
              onChange={(next) => {
                setInto(next);
                setConfirmed(false);
                setChanged(false);
              }}
              from={{
                id: item.id,
                requesterId: item.requester_id,
                requesterName: personName(item.people, item.requester_id),
              }}
              testId="inc-merge-into"
              ariaLabel={t('incidents.merge.into')}
            />
          </Form.Item>
        </Form>
        {into !== null &&
          (preview.isLoading ? (
            <Skeleton active paragraph={{ rows: 2 }} />
          ) : preview.isError ? (
            <Refused error={preview.error} testId="inc-merge-refused" />
          ) : preview.data !== undefined ? (
            <>
              {changed && (
                <Alert
                  type="warning"
                  showIcon
                  role="alert"
                  data-testid="inc-merge-changed"
                  message={t('incidents.merge.audience_changed')}
                />
              )}
              <Audience preview={preview.data} />
              {needs && (
                <Checkbox
                  checked={confirmed}
                  onChange={(event) => {
                    setConfirmed(event.target.checked);
                  }}
                  data-testid="inc-merge-wider-ok"
                >
                  {t('incidents.merge.confirm_wider')}
                </Checkbox>
              )}
            </>
          ) : null)}
      </Flex>
    </Modal>
  );
}

/**
 * A merged or converted record says where it went (the other side hidden when this person may
 * not see it); a merged one offers undo to those with the right. The server asks for a recent
 * sign-in itself; the API client shows that prompt.
 */
export function MovedBanner({
  item,
  kind,
}: {
  item: Pick<Incident, 'id' | 'status' | 'version' | 'display_id'>;
  kind: ConvertibleKind;
}) {
  const t = useLabel();
  const merged = item.status === 'merged';
  const converted = item.status === 'converted';
  const links = useMovedLinks(kind, item.id, merged || converted);
  const undo = useUndoMerge(item.id);
  if (!merged && !converted) return null;
  const relation = merged ? 'merged_into' : 'converted_to';
  const where = (links.data ?? []).find((link) => link.relation === relation);
  const other =
    where === undefined ? null : where.other_id === null ? (
      <span data-testid="inc-moved-hidden">{t('incidents.moved.hidden')}</span>
    ) : (
      <Link
        to={`/${RECORD_PATHS[where.other_type ?? 'incident'] ?? 'incidents'}/${where.other_id}`}
        data-testid="inc-moved-link"
      >
        <bdi dir="ltr">{where.other_display_id}</bdi> <bdi dir="auto">{where.other_subject}</bdi>
      </Link>
    );
  return (
    <Alert
      type="info"
      showIcon
      role="status"
      data-testid="inc-moved"
      message={
        <span>
          {t(merged ? 'incidents.moved.merged' : 'incidents.moved.converted')} {other}
        </span>
      }
      action={
        merged && kind === 'incidents' ? (
          // Asked first (lane C): undo moves children and followers back.
          <Popconfirm
            title={t('incidents.moved.undo_confirm', { id: item.display_id })}
            okText={t('incidents.moved.undo')}
            cancelText={t('actions.cancel')}
            okButtonProps={{ 'data-testid': 'inc-undo-merge-ok' }}
            onConfirm={() => {
              undo.mutate(item.version, { onError: reportError });
            }}
          >
            <WriteButton size="small" loading={undo.isPending} data-testid="inc-undo-merge">
              {t('incidents.moved.undo')}
            </WriteButton>
          </Popconfirm>
        ) : undefined
      }
    />
  );
}

/** The fields left behind, by name: the conversion keeps them on the original. */
function LeftBehind({ kind, keys }: { kind: ConvertibleKind; keys: string[] }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const fields = useCustomFields(kind === 'incidents' ? 'incident' : 'service_request', true);
  if (keys.length === 0) return null;
  const names = keys.map((key) => {
    const field = fields.data?.find((f) => f.key === key);
    return field === undefined ? t('incidents.convert.unnamed_field') : fieldName(field, locale);
  });
  return (
    <Alert
      type="warning"
      showIcon
      data-testid="inc-convert-left"
      message={t('incidents.convert.left_behind', { count: keys.length })}
      description={
        <ul style={{ margin: 0, paddingInlineStart: 20 }}>
          {names.map((name, index) => (
            <li key={keys[index]}>
              <bdi dir="auto">{name}</bdi>
            </li>
          ))}
        </ul>
      }
    />
  );
}

/** What a request needs from its catalog item: the item and the requester's answers. */
function ItemAnswers({
  itemId,
  onItem,
  answers,
  onAnswers,
}: {
  itemId: string | null;
  onItem: (id: string | null) => void;
  answers: Record<string, QuestionValue> | null;
  onAnswers: (next: Record<string, QuestionValue>) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const items = useCatalogItems();
  const chosen = useCatalogItem(itemId ?? undefined);
  const questions = requesterQuestions(chosen.data?.questions ?? []);
  const shown = answers ?? startingAnswers(questions);
  return (
    <Form layout="vertical" component="div">
      <Form.Item label={t('incidents.convert.item')} htmlFor="inc-convert-item" required>
        <Select
          id="inc-convert-item"
          showSearch
          optionFilterProp="label"
          value={itemId}
          onChange={(next: string) => {
            onItem(next);
          }}
          loading={items.isLoading}
          aria-label={t('incidents.convert.item')}
          data-testid="inc-convert-item"
          options={(items.data ?? []).map((i) => ({ value: i.id, label: itemName(i, locale) }))}
        />
      </Form.Item>
      {questions.map((q) => (
        <Form.Item
          key={q.key}
          label={textIn(q.label, locale) || t('incidents.convert.unnamed_field')}
          extra={textIn(q.help, locale) || undefined}
          htmlFor={`sr-q-${q.key}`}
          required={q.required}
        >
          <QuestionField
            question={q}
            value={shown[q.key] ?? null}
            onChange={(value) => {
              onAnswers({ ...shown, [q.key]: value });
            }}
            locale={locale}
            renderPerson={({ id, value, onChange, disabled }) => (
              <UserPicker
                id={id}
                value={value}
                onChange={onChange}
                disabled={disabled}
                testId={id}
                ariaLabel={textIn(q.label, locale)}
              />
            )}
          />
        </Form.Item>
      ))}
    </Form>
  );
}

/** The required answers still empty. */
function missingAnswers(
  questions: ReturnType<typeof requesterQuestions>,
  answers: Record<string, QuestionValue>,
): boolean {
  return questions.some((q) => {
    const value = answers[q.key];
    return (
      q.required && (value == null || value === '' || (Array.isArray(value) && value.length === 0))
    );
  });
}

/**
 * Convert an incident into a service request (a catalog item and its answers) or a request
 * into an incident (a template). A new record is made; this one becomes converted, read-only,
 * linked to it, and its old number leads there.
 */
export function ConvertDialog({
  kind,
  record,
  open,
  onClose,
}: {
  kind: ConvertibleKind;
  record: { id: string; display_id: string; version: number };
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const preview = useConvertPreview(kind, record.id, open);
  const convert = useConvertRecord(kind, record.id);
  const [itemId, setItemId] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, QuestionValue> | null>(null);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const templates = useIncidentTemplates(open && kind === 'service-requests');
  const chosen = useCatalogItem(itemId ?? undefined);
  const questions = requesterQuestions(chosen.data?.questions ?? []);
  const shown = answers ?? startingAnswers(questions);
  const toRequest = kind === 'incidents';
  const ready = toRequest
    ? itemId !== null && chosen.data !== undefined && !missingAnswers(questions, shown)
    : true;
  const close = () => {
    setItemId(null);
    setAnswers(null);
    setTemplateId(null);
    onClose();
  };
  return (
    <Modal
      open={open}
      title={t(toRequest ? 'incidents.convert.to_request' : 'incidents.convert.to_incident', {
        id: record.display_id,
      })}
      onCancel={close}
      destroyOnHidden
      okText={t('incidents.convert.confirm')}
      cancelText={t('actions.cancel')}
      okButtonProps={{
        disabled: !ready || preview.data === undefined,
        loading: convert.isPending,
        'data-testid': 'inc-convert-confirm',
      }}
      onOk={() => {
        convert.mutate(
          toRequest
            ? {
                catalogItemId: itemId ?? undefined,
                answers: sentAnswers(shown),
                version: record.version,
              }
            : { templateId: templateId ?? undefined, version: record.version },
          {
            onSuccess: (made) => {
              close();
              void navigate(`/${RECORD_PATHS[made.new_type] ?? 'incidents'}/${made.new_id}`);
            },
            onError: reportError,
          },
        );
      }}
    >
      <Flex vertical gap={12} data-testid="inc-convert-dialog">
        <Typography.Paragraph style={{ margin: 0 }}>
          {t('incidents.convert.explain')}
        </Typography.Paragraph>
        {preview.isLoading ? (
          <Skeleton active paragraph={{ rows: 2 }} />
        ) : preview.isError ? (
          <Refused error={preview.error} testId="inc-convert-refused" />
        ) : preview.data !== undefined ? (
          <>
            <LeftBehind kind={kind} keys={preview.data.not_carried} />
            {preview.data.pending_approvals && (
              <Alert
                type="warning"
                showIcon
                data-testid="inc-convert-approvals"
                message={t('incidents.convert.approvals_withdrawn')}
              />
            )}
          </>
        ) : null}
        {toRequest ? (
          <ItemAnswers
            itemId={itemId}
            onItem={(next) => {
              setItemId(next);
              setAnswers(null);
            }}
            answers={answers}
            onAnswers={setAnswers}
          />
        ) : (
          <Form layout="vertical" component="div">
            <Form.Item label={t('incidents.convert.template')} htmlFor="inc-convert-template">
              <Select
                id="inc-convert-template"
                allowClear
                value={templateId}
                onChange={(next: string | undefined) => {
                  setTemplateId(next ?? null);
                }}
                aria-label={t('incidents.convert.template')}
                placeholder={t('incidents.convert.default_template')}
                data-testid="inc-convert-template"
                options={(templates.data ?? []).map((tpl) => ({
                  value: tpl.id,
                  label: templateLabel(t, tpl, locale),
                }))}
              />
            </Form.Item>
          </Form>
        )}
      </Flex>
    </Modal>
  );
}
