import { App, Button, Flex, Modal, Space, Spin, Table, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';

import {
  REDACT_MAX,
  fetchPassage,
  useErasureActions,
  useErasureMentions,
  type Erasure,
  type ErasureMention,
  type MentionMatchKind,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  ConflictDialog,
  FilterBar,
  ListNotice,
  ToneTag,
  loadedEmpty,
  useAppearance,
  useConflictRetry,
  useDateTime,
  useLabel,
} from '@supportx/ui';

import { fieldLabel, marked, moduleLabel, recordTypeLabel, useErasureProblem } from './erasureText';
import { PersonName } from './words';

const KINDS: readonly MentionMatchKind[] = ['name', 'email', 'phone'];
const CHANGEABLE = new Set(['requested', 'approved']);

/**
 * The mentions report (ADR-052 S1b, D-171 a): where the person is named in other people's text,
 * by module and kind, then place by place. Text is shown only on demand, one passage at a time,
 * and dropped when the passage closes. Redaction acts on the selected places (at most 200).
 */
export function MentionsReport({
  erasure,
  personName,
  personEmail,
}: {
  erasure: Erasure;
  /** For marking the match in a passage and the short-name note; absent once erased. */
  personName?: string;
  personEmail?: string;
}) {
  const t = useLabel();
  const list = useListFormat();
  const dates = useDateTime();
  const { modal, message } = App.useApp();
  const report = erasure.report;
  const mentions = useErasureMentions(erasure.id);
  const { review, redact } = useErasureActions(erasure.id);
  const retry = useConflictRetry();
  const problemOf = useErasureProblem();
  const [selected, setSelected] = useState<string[]>([]);
  const [passage, setPassage] = useState<ErasureMention>();
  const rows = useMemo(() => mentions.data?.pages.flatMap((p) => p.items) ?? [], [mentions.data]);
  const changeable = CHANGEABLE.has(erasure.state);
  const missing = report?.ports_missing ?? [];

  const markReviewed = (version: number) => {
    review.mutate(
      { version },
      {
        onSuccess: () => {
          void message.success(t('people_erasure.report_reviewed'));
        },
        onError: (error) => {
          if (!retry.take(error, markReviewed)) void message.error(problemOf(error));
        },
      },
    );
  };
  const sendRedact = (version: number, ids: string[]) => {
    redact.mutate(
      { version, mentionIds: ids },
      {
        onSuccess: () => {
          setSelected([]);
          void message.success(t('people_erasure.redacted'));
        },
        onError: (error) => {
          if (
            !retry.take(error, (v) => {
              sendRedact(v, ids);
            })
          )
            void message.error(problemOf(error));
        },
      },
    );
  };
  const askRedact = () => {
    const ids = selected.slice(0, REDACT_MAX);
    void modal.confirm({
      title: t('people_erasure.redact_confirm', { n: ids.length }),
      content: t('people_erasure.redact_explain'),
      okText: t('people_erasure.redact_ok'),
      okButtonProps: { danger: true, id: 'erasure-redact-ok' },
      cancelText: t('actions.cancel'),
      onOk: () => {
        sendRedact(erasure.version, ids);
      },
    });
  };

  const selection =
    selected.length > 0 ? (
      <Space wrap data-testid="erasure-mentions-selection">
        <Typography.Text>
          {t('people_erasure.selected', { n: selected.length, max: REDACT_MAX })}
        </Typography.Text>
        <Button danger onClick={askRedact} data-testid="erasure-redact">
          {t('people_erasure.redact_selected')}
        </Button>
        <Button
          type="link"
          onClick={() => {
            setSelected([]);
          }}
        >
          {t('people_erasure.cancel_selection')}
        </Button>
      </Space>
    ) : undefined;

  return (
    <Flex vertical gap={16} data-testid="erasure-mentions">
      {(report === null || report.building) && (
        <ListNotice testId="erasure-report-building">
          {t('people_erasure.report.building')}
        </ListNotice>
      )}
      {missing.length > 0 && (
        <ListNotice testId="erasure-report-missing">
          {t('people_erasure.report.ports_missing', {
            modules: list(missing.map((m) => moduleLabel(t, m))),
          })}
        </ListNotice>
      )}
      {report != null && <ReportTable byModule={report.by_module} />}
      {/* Fixed notes, always shown (D-171 a): what the search does not reach. */}
      <Flex vertical gap={4} data-testid="erasure-report-notes">
        <Typography.Text type="secondary">
          {t('people_erasure.attachment_content_not_searched')}
        </Typography.Text>
        <Typography.Text type="secondary">
          {t('people_erasure.mail_bodies_not_searched')}
        </Typography.Text>
        {report?.short_name_not_searched === true && (
          <Typography.Text type="secondary" data-testid="erasure-short-name">
            {personName === undefined
              ? t('people_erasure.short_name_not_searched_erased')
              : t('people_erasure.short_name_not_searched', { name: personName })}
          </Typography.Text>
        )}
      </Flex>
      <Flex gap={8} align="center" wrap>
        {report?.reviewed_at != null ? (
          <Typography.Text data-testid="erasure-reviewed">
            {t('people_erasure.reviewed_by')}: <PersonName id={report.reviewed_by ?? null} />
            {' · '}
            <span title={dates.format(report.reviewed_at)}>
              {dates.relative(report.reviewed_at)}
            </span>
          </Typography.Text>
        ) : (
          changeable &&
          report?.complete === true && (
            <Button
              onClick={() => {
                markReviewed(erasure.version);
              }}
              loading={review.isPending}
              data-testid="erasure-mark-reviewed"
            >
              {t('people_erasure.mark_reviewed')}
            </Button>
          )
        )}
      </Flex>
      <FilterBar testId="erasure-mentions-bar" selection={selection} />
      <Table<ErasureMention>
        rowKey="id"
        data-testid="erasure-mentions-table"
        loading={mentions.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 820 }}
        locale={{ emptyText: loadedEmpty(mentions.isPending, t('people_erasure.mentions_none')) }}
        rowSelection={
          changeable
            ? {
                selectedRowKeys: selected,
                onChange: (keys) => {
                  setSelected(keys.map(String).slice(0, REDACT_MAX));
                },
                getCheckboxProps: (r) => ({
                  disabled: r.state !== 'found',
                  'aria-label': t('people_erasure.select_mention'),
                }),
              }
            : undefined
        }
        columns={[
          {
            key: 'module',
            title: t('people_erasure.mention.module'),
            render: (_, r) => moduleLabel(t, r.module_key),
          },
          {
            key: 'record',
            title: t('people_erasure.mention.record'),
            render: (_, r) => recordTypeLabel(t, r.record_type),
          },
          {
            key: 'field',
            title: t('people_erasure.mention.field'),
            render: (_, r) => (
              <Flex vertical>
                <span>{fieldLabel(t, r.field)}</span>
                {r.reaches_record_history && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t('people_erasure.reaches_record_history')}
                  </Typography.Text>
                )}
                {r.history_kept > 0 && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t('people_erasure.history_kept_fingerprinted')}
                  </Typography.Text>
                )}
              </Flex>
            ),
          },
          {
            key: 'kind',
            title: t('people_erasure.mention.kind'),
            render: (_, r) => t(`people_erasure.match_kind.${r.match_kind}`),
          },
          {
            key: 'occurrences',
            title: t('people_erasure.mention.occurrences'),
            render: (_, r) => <bdi dir="ltr">{r.occurrences}</bdi>,
          },
          {
            key: 'state',
            title: t('people_erasure.mention.state'),
            render: (_, r) => (
              <ToneTag tone={r.state === 'redacted' ? 'success' : 'default'}>
                {t(`people_erasure.mention_state.${r.state}`)}
              </ToneTag>
            ),
          },
          {
            key: 'passage',
            title: '',
            render: (_, r) => (
              <Button
                type="link"
                onClick={() => {
                  setPassage(r);
                }}
                data-testid={`erasure-passage-${r.id}`}
              >
                {t('people_erasure.mention.show_passage')}
              </Button>
            ),
          },
        ]}
      />
      {mentions.hasNextPage && (
        <Button
          onClick={() => void mentions.fetchNextPage()}
          loading={mentions.isFetchingNextPage}
          data-testid="erasure-mentions-more"
        >
          {t('people_erasure.load_more')}
        </Button>
      )}
      {passage !== undefined && (
        <PassageDialog
          key={passage.id}
          erasureId={erasure.id}
          mention={passage}
          terms={[personName, personEmail].filter((s): s is string => s !== undefined && s !== '')}
          onClose={() => {
            setPassage(undefined);
          }}
        />
      )}
      <ConflictDialog {...retry.dialog} />
    </Flex>
  );
}

/** Module × kind counts: a header row with `scope`, numbers in the reader's locale. */
function ReportTable({ byModule }: { byModule: Record<string, Record<string, number>> }) {
  const t = useLabel();
  const { intlLocale } = useAppearance();
  const number = new Intl.NumberFormat(intlLocale);
  const modules = Object.keys(byModule);
  if (modules.length === 0) return null;
  const total = (kinds: Record<string, number>) =>
    Object.values(kinds).reduce((sum, n) => sum + n, 0);
  return (
    <table className="sx-plain-table" data-testid="erasure-report-table" style={{ width: '100%' }}>
      <thead>
        <tr>
          <th scope="col" style={{ textAlign: 'start' }}>
            {t('people_erasure.report.module')}
          </th>
          {KINDS.map((k) => (
            <th scope="col" key={k} style={{ textAlign: 'end' }}>
              {t(`people_erasure.match_kind.${k}`)}
            </th>
          ))}
          <th scope="col" style={{ textAlign: 'end' }}>
            {t('people_erasure.report.total')}
          </th>
        </tr>
      </thead>
      <tbody>
        {modules.map((m) => {
          const kinds = byModule[m] ?? {};
          return (
            <tr key={m}>
              <th scope="row" style={{ textAlign: 'start', fontWeight: 'normal' }}>
                {moduleLabel(t, m)}
              </th>
              {KINDS.map((k) => (
                <td key={k} style={{ textAlign: 'end' }}>
                  {number.format(kinds[k] ?? 0)}
                </td>
              ))}
              <td style={{ textAlign: 'end' }}>{number.format(total(kinds))}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * One passage, fetched when it opens and dropped when it closes: the caller mounts it only while
 * open, one per mention (`key`), so its text goes with it (never cached or stored; the server
 * audits each view). 404 or an empty answer: "You can't read this record".
 */
function PassageDialog({
  erasureId,
  mention,
  terms,
  onClose,
}: {
  erasureId: string;
  mention: ErasureMention;
  terms: readonly string[];
  onClose: () => void;
}) {
  const t = useLabel();
  // undefined: still loading; null: you can't read it.
  const [text, setText] = useState<string | null>();
  useEffect(() => {
    let live = true;
    fetchPassage(erasureId, mention.id).then(
      (found) => {
        if (live) setText(found.text === '' ? null : found.text);
      },
      () => {
        // 404 (your rights don't reach the record) and any other refusal say only that: no
        // fact about the record leaks through the error.
        if (live) setText(null);
      },
    );
    return () => {
      live = false;
    };
  }, [erasureId, mention.id]);
  return (
    <Modal
      open
      title={t('people_erasure.passage.title')}
      onCancel={onClose}
      footer={
        <Button onClick={onClose} data-testid="erasure-passage-close">
          {t('people_erasure.passage.close')}
        </Button>
      }
      destroyOnHidden
      data-testid="erasure-passage"
    >
      <Flex vertical gap={8}>
        {text === undefined ? (
          <Spin />
        ) : text === null ? (
          <Typography.Text data-testid="erasure-passage-none">
            {t('people_erasure.passage.no_access')}
          </Typography.Text>
        ) : (
          <Typography.Paragraph
            data-testid="erasure-passage-text"
            style={{ whiteSpace: 'pre-wrap' }}
          >
            <bdi dir="auto">{marked(text, terms)}</bdi>
          </Typography.Paragraph>
        )}
        <Typography.Text type="secondary">{t('people_erasure.passage.note')}</Typography.Text>
      </Flex>
    </Modal>
  );
}
