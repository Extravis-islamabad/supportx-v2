import {
  DownOutlined,
  ExclamationCircleOutlined,
  GlobalOutlined,
  LockOutlined,
  SendOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Avatar,
  Button,
  Card,
  Dropdown,
  Modal,
  Empty,
  Flex,
  Popconfirm,
  Radio,
  Segmented,
  Select,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  Typography,
  theme,
} from 'antd';
import { cloneElement, isValidElement, useMemo, useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';

import {
  ApiError,
  attachDrafts,
  fetchMentionable,
  queryKeys,
  useAddConversationEntry,
  useChangeNoteVisibility,
  useFiles,
  useIncidentConversation,
  useRecordFiles,
  useReplyTemplates,
  useSession,
  type ConversationEntry,
  type StoredFile,
  type EntryKind,
  type Incident,
  type ReplyMode,
  type Visibility,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import {
  Attachments,
  ConflictDialog,
  describeError,
  FormProblem,
  inlineImageIds,
  markHandled,
  reportError,
  RichTextField,
  RichTextView,
  ToneTag,
  useAccess,
  useConflictRetry,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
  type MentionSearch,
} from '@supportx/ui';

import { useTenantChannel } from '@supportx/realtime';

import { useIncidentFieldName } from './conflict';
import { useTypingSignal } from './typing';

type Filter = 'all' | 'messages' | 'notes' | 'system';
type Draft = { kind: 'reply'; mode: ReplyMode } | { kind: 'note' };

/** Where admins manage reply templates (WP-020c: moved out of the composer). */
const REPLY_TEMPLATES_SETTINGS = '/admin/incidents/reply-templates';

/** Who is writing what right now, from typing signals on the record channel (REQ-WI-006 AC2). */
export type Typing = Record<string, { name: string; kind: EntryKind }>;

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0))
    .join('')
    .toUpperCase();
}

/**
 * The conversation (REQ-INC-057): the description, replies and notes in time order, live.
 * Public and private entries look different in every view (REQ-INC-061): a private note has a
 * lock, a tinted background and says "staff only"; a public one a globe and "requester can see".
 * Replies made before the email channel exists say plainly they were not sent (WP-024).
 */
export function IncidentConversation({ item, typing }: { item: Incident; typing: Typing }) {
  const t = useLabel();
  const listFormat = useListFormat();
  const [filter, setFilter] = useState<Filter>('all');
  const [draft, setDraft] = useState<Draft | null>(null);
  const conversation = useIncidentConversation(item.id);
  const recordFiles = useRecordFiles('incident', item.id).data ?? [];
  const entries = conversation.data?.items ?? [];
  const people = conversation.data?.people ?? {};
  const shown = entries.filter(
    (e) =>
      filter === 'all' ||
      (filter === 'messages' && e.kind === 'reply') ||
      (filter === 'notes' && e.kind === 'note'),
  );
  const writers = Object.entries(typing);
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Segmented<Filter>
          value={filter}
          onChange={setFilter}
          aria-label={t('conversation.filter')}
          options={(['all', 'messages', 'notes', 'system'] as const).map((f) => ({
            value: f,
            label: t(`conversation.filter.${f}`),
          }))}
          data-testid="conv-filter"
        />
        <ComposeButtons item={item} onCompose={setDraft} disabled={draft !== null} />
      </Flex>
      <div aria-live="polite" data-testid="conv-typing" style={{ minHeight: 22 }}>
        {writers.length > 0 && (
          <Typography.Text type="secondary" italic>
            {writers.length === 1
              ? t(`conversation.typing.${writers[0]?.[1].kind ?? 'note'}`, {
                  name: writers[0]?.[1].name ?? '',
                })
              : t('conversation.typing.several', {
                  names: listFormat(
                    writers.map(([, w]) => w.name),
                    'conjunction',
                  ),
                })}
          </Typography.Text>
        )}
      </div>
      {draft !== null && (
        <Composer
          key={draft.kind === 'note' ? 'note' : `reply-${draft.mode}`}
          item={item}
          draft={draft}
          entries={entries}
          onDone={() => {
            setDraft(null);
          }}
        />
      )}
      {conversation.isPending ? (
        <Skeleton active />
      ) : (
        <Flex vertical gap={12} data-testid="conv-timeline">
          {(filter === 'all' || filter === 'messages') && <DescriptionEntry item={item} />}
          {conversation.data?.truncated === true && (
            <Alert type="info" showIcon message={t('conversation.truncated')} />
          )}
          {shown.map((entry) => (
            <EntryCard
              key={entry.id}
              item={item}
              entry={entry}
              people={people}
              files={recordFiles.filter(
                (file) =>
                  file.owner_type === 'conversation_entry' &&
                  file.owner_id === entry.id &&
                  !file.inline,
              )}
            />
          ))}
          {filter === 'system' && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <Typography.Text type="secondary">{t('conversation.system_empty')}</Typography.Text>
              }
            />
          )}
          {filter !== 'system' && filter !== 'all' && shown.length === 0 && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <Typography.Text type="secondary">
                  {t(`conversation.empty.${filter}`)}
                </Typography.Text>
              }
            />
          )}
        </Flex>
      )}
    </Space>
  );
}

function ComposeButtons({
  item,
  onCompose,
  disabled,
}: {
  item: Incident;
  onCompose: (draft: Draft) => void;
  disabled: boolean;
}) {
  const t = useLabel();
  const state = (name: string) => item.conversation_actions.find((a) => a.action === name);
  const reply = state('reply');
  const note = state('add_note');
  const why = (s: typeof reply) =>
    s === undefined || s.allowed ? undefined : t(`action_reason.${s.reason ?? 'no_permission'}`);
  // Opens on click (keyboard too) and closes once something is chosen (QA BUG-10).
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <Space wrap>
      <Tooltip title={why(reply)}>
        <Dropdown.Button
          type="primary"
          disabled={disabled || reply?.allowed !== true}
          icon={<DownOutlined />}
          trigger={['click']}
          open={menuOpen}
          onOpenChange={setMenuOpen}
          onClick={() => {
            onCompose({ kind: 'reply', mode: 'reply' });
          }}
          menu={{
            items: (['reply_all', 'forward'] as const).map((mode) => ({
              key: mode,
              label: t(`reply_mode.${mode}`),
            })),
            onClick: ({ key }) => {
              setMenuOpen(false);
              onCompose({ kind: 'reply', mode: key as ReplyMode });
            },
          }}
          buttonsRender={([left, right]) => [
            <span key="l" data-testid="conv-reply">
              {left}
            </span>,
            <span key="r" data-testid="conv-reply-more" aria-label={t('conversation.more_reply')}>
              {/* Ant Design disables only the left part; the arrow must look disabled too. */}
              {isValidElement<{ disabled?: boolean }>(right)
                ? cloneElement(right, { disabled: disabled || reply?.allowed !== true })
                : right}
            </span>,
          ]}
        >
          <SendOutlined /> {t('reply_mode.reply')}
        </Dropdown.Button>
      </Tooltip>
      <Tooltip title={why(note)}>
        <WriteButton
          disabled={disabled || note?.allowed !== true}
          onClick={() => {
            onCompose({ kind: 'note' });
          }}
          data-testid="conv-add-note"
        >
          {t('conversation.add_note')}
        </WriteButton>
      </Tooltip>
    </Space>
  );
}

function DescriptionEntry({ item }: { item: Incident }) {
  const t = useLabel();
  const dates = useDateTime();
  const { token } = theme.useToken();
  const author = item.people[item.created_by ?? '']?.display_name ?? '';
  return (
    <Card
      size="small"
      data-testid="conv-description"
      style={{ borderInlineStart: `4px solid ${token.colorBorder}` }}
    >
      <Flex justify="space-between" wrap gap={8}>
        <Space size={6} wrap>
          <Avatar size="small" style={{ background: token.colorPrimary }}>
            {initials(author)}
          </Avatar>
          <Typography.Text strong>
            <bdi dir="auto">{author}</bdi>
          </Typography.Text>
          <Tag>{t('conversation.kind.description')}</Tag>
          <Tag icon={<GlobalOutlined />}>{t(`work_item_channel.${item.channel}`)}</Tag>
        </Space>
        <Typography.Text type="secondary">{dates.format(item.created_at)}</Typography.Text>
      </Flex>
      <div style={{ marginTop: 8 }}>
        {item.description === null || item.description === '' ? (
          <Typography.Text type="secondary">{t('conversation.no_description')}</Typography.Text>
        ) : (
          <RichTextView html={item.description} />
        )}
      </div>
    </Card>
  );
}

function EntryCard({
  item,
  entry,
  people,
  files,
}: {
  item: Incident;
  entry: ConversationEntry;
  people: Record<string, { display_name: string; email: string }>;
  files: StoredFile[];
}) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { can } = useAccess();
  const canEditRecord = item.operations.find((o) => o.action === 'edit')?.allowed === true;
  const dates = useDateTime();
  const { token } = theme.useToken();
  const { message } = App.useApp();
  const change = useChangeNoteVisibility(item.id);
  // Changed by someone after it was shown (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflictRetry();
  const fieldName = useIncidentFieldName();
  const switchTo = (visibility: Visibility, version: number) => {
    change.mutate(
      { entryId: entry.id, visibility, version },
      {
        onSuccess: () => void message.success(t(`conversation.made_${visibility}`)),
        onError: (error) => {
          if (
            !conflict.take(error, (at) => {
              switchTo(visibility, at);
            })
          )
            reportError(error);
        },
      },
    );
  };
  const author = people[entry.created_by ?? '']?.display_name ?? t('conversation.someone');
  const isPrivate = entry.visibility === 'private';
  const accent = isPrivate
    ? token.colorWarning
    : entry.kind === 'reply'
      ? token.colorPrimary
      : token.colorInfo;
  const kindKey =
    entry.kind === 'reply'
      ? `reply_mode.${entry.reply_mode ?? 'reply'}`
      : isPrivate
        ? 'conversation.kind.private_note'
        : 'conversation.kind.public_note';
  const canSwitch =
    entry.kind === 'note' &&
    item.conversation_actions.find((a) => a.action === 'reply')?.allowed === true;
  const next: Visibility = isPrivate ? 'public' : 'private';
  return (
    <Card
      size="small"
      data-testid="conv-entry"
      data-kind={entry.kind}
      data-visibility={entry.visibility}
      style={{
        borderInlineStart: `4px solid ${accent}`,
        background: isPrivate ? token.colorWarningBg : undefined,
      }}
    >
      <Flex justify="space-between" wrap gap={8}>
        <Space size={6} wrap>
          <Avatar size="small" style={{ background: token.colorPrimary }}>
            {initials(author)}
          </Avatar>
          <Typography.Text strong>
            <bdi dir="auto">{author}</bdi>
          </Typography.Text>
          <ToneTag
            icon={isPrivate ? <LockOutlined /> : <GlobalOutlined />}
            tone={isPrivate ? 'warning' : entry.kind === 'reply' ? 'purple' : 'info'}
            testId="conv-entry-visibility"
          >
            {t(kindKey)}
          </ToneTag>
          <Typography.Text type={isPrivate ? undefined : 'secondary'} data-testid="conv-entry-who">
            {t(isPrivate ? 'conversation.private_hint' : 'conversation.public_hint')}
          </Typography.Text>
          {entry.first_response && (
            <ToneTag tone="success" testId="conv-first-response">
              {t('conversation.first_response')}
            </ToneTag>
          )}
          {entry.delivery_state === 'received' && (
            // The requester's own words, sent in from the portal or by e-mail (QA BUG-01).
            <ToneTag tone="info" testId="conv-received">
              {t('delivery_state.received')}
            </ToneTag>
          )}
        </Space>
        <Typography.Text type="secondary">{dates.format(entry.created_at)}</Typography.Text>
      </Flex>
      {entry.kind === 'reply' && entry.recipients !== null && (
        <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
          {t('conversation.to')}: <bdi>{listFormat(entry.recipients.to)}</bdi>
          {entry.recipients.cc.length > 0 && (
            <>
              {' · '}
              {t('conversation.cc')}: <bdi>{listFormat(entry.recipients.cc)}</bdi>
            </>
          )}
        </Typography.Paragraph>
      )}
      {entry.delivery_state === 'not_sent' && (
        <Alert
          type="warning"
          showIcon
          icon={<ExclamationCircleOutlined />}
          style={{ marginTop: 8 }}
          data-testid="conv-not-sent"
          message={t('conversation.not_sent', {
            reason: t(`delivery_reason.${entry.delivery_reason ?? 'email_channel_not_configured'}`),
          })}
          description={t('conversation.not_sent_detail')}
        />
      )}
      <div style={{ marginTop: 8 }}>
        <RichTextView html={entry.body} />
      </div>
      {files.length > 0 && (
        <Attachments
          files={files}
          canRemove={canEditRecord}
          canRescan={can('files.manage')}
          staffOnly={isPrivate}
          testId="conv-entry-files"
        />
      )}
      {canSwitch && (
        <Flex justify="end">
          <Popconfirm
            title={t(`conversation.make_${next}_title`)}
            description={t(`conversation.make_${next}_text`)}
            okText={t(`conversation.make_${next}`)}
            cancelText={t('actions.cancel')}
            onConfirm={() => {
              switchTo(next, entry.version);
            }}
          >
            <Button size="small" type="link" data-testid="conv-switch-visibility">
              {t(`conversation.make_${next}`)}
            </Button>
          </Popconfirm>
        </Flex>
      )}
      <ConflictDialog {...conflict.dialog} fieldLabel={fieldName} />
    </Card>
  );
}

function emailsOf(
  ids: (string | null)[],
  people: Record<string, { display_name: string; email: string }>,
): string[] {
  return ids
    .map((id) => (id === null ? '' : (people[id]?.email ?? '')))
    .filter((e) => e !== '')
    .map((e) => e.toLowerCase());
}

/** The composer: a reply (to, cc) or a note (private by default, D-079). */
function Composer({
  item,
  draft,
  entries,
  onDone,
}: {
  item: Incident;
  draft: Draft;
  entries: ConversationEntry[];
  onDone: () => void;
}) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { message } = App.useApp();
  const { can } = useAccess();
  const add = useAddConversationEntry(item.id);
  const templates = useReplyTemplates();
  const me = useSession().data?.user.id;
  // Files for this entry wait as the author's drafts until it is saved (WP-022).
  const [draftIds, setDraftIds] = useState<string[]>([]);
  const drafts = useFiles(draftIds);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [body, setBody] = useState('');
  const [visibility, setVisibility] = useState<Visibility>('private');
  const requesters = emailsOf([item.requester_id, item.on_behalf_of_id], item.people);
  const initial = useMemo(() => {
    if (draft.kind === 'note' || draft.mode === 'forward') return { to: [], cc: [] };
    if (draft.mode === 'reply') return { to: requesters, cc: [] };
    // Reply all: the requester, and everyone the last reply went to.
    const last = [...entries].reverse().find((e) => e.kind === 'reply' && e.recipients !== null);
    const others = [...(last?.recipients?.to ?? []), ...(last?.recipients?.cc ?? [])].filter(
      (e) => !requesters.includes(e),
    );
    return { to: requesters, cc: [...new Set(others)] };
    // Fixed when the composer opens; the user edits from there.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- computed once per composer
  }, []);
  const [to, setTo] = useState<string[]>(initial.to);
  const [cc, setCc] = useState<string[]>(initial.cc);
  const kind: EntryKind = draft.kind;
  // Typing signal: start, repeated while typing goes on, stop after a pause (QA BUG-04).
  const { typed, stop: stopTyping } = useTypingSignal(item.id, kind);
  // Templates changed by an admin elsewhere: reload the list while this composer is open (BUG-07).
  const queryClient = useQueryClient();
  useTenantChannel((message) => {
    if (message.type === 'work_items.reply_templates_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.replyTemplates });
    }
  });
  // D-081: warn before sending a mention of someone who cannot see the incident.
  const [unseen, setUnseen] = useState<string[] | null>(null);
  const mentions: MentionSearch = (query) =>
    fetchMentionable(item.id, query).then((found) =>
      found.map((p) => ({ id: p.id, label: p.display_name, email: p.email, canSee: p.can_see })),
    );
  const error = add.error instanceof ApiError ? add.error : null;
  const fieldErrors = error?.status === 422 ? error.fieldErrors : [];
  // Any other refusal (a rule, a limit) is shown here too, not as a toast (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const send = (confirmed = false) => {
    const blind = cannotSee(body);
    if (!confirmed && blind.length > 0) {
      setUnseen(blind);
      return;
    }
    setUnseen(null);
    stopTyping();
    problem.clear();
    const clean = withoutComposerMarkers(body);
    add.mutate(
      {
        key,
        body:
          kind === 'reply' && draft.kind === 'reply'
            ? { kind, body: clean, reply_mode: draft.mode, to, cc }
            : { kind, body: clean, visibility },
      },
      {
        onSuccess: (saved) => {
          attachDrafts('conversation_entry', saved.entry.id, [...draftIds, ...inlineImageIds(body)])
            .then(() =>
              queryClient.invalidateQueries({
                queryKey: queryKeys.files.record('incident', item.id),
              }),
            )
            .catch(reportError);
          if (saved.entry.delivery_state === 'not_sent') {
            void message.warning(t('conversation.reply_saved_not_sent'));
          } else {
            void message.success(t(`conversation.saved.${saved.entry.kind}`));
          }
          // A requester's late reply started a new incident that follows this one (REQ-INC-098).
          if (saved.follow_up != null) {
            void message.info(
              t('conversation.follow_up_started', { id: saved.follow_up.display_id }),
            );
          }
          if (saved.not_notified.length > 0) {
            void message.warning(
              t('conversation.mention_not_notified', {
                names: listFormat(
                  saved.not_notified.map((id) => saved.people[id]?.display_name ?? ''),
                  'conjunction',
                ),
              }),
            );
          }
          onDone();
        },
        onError: (failure) => {
          setKey(crypto.randomUUID()); // corrected input is a new request
          if (failure instanceof ApiError && failure.status === 422) markHandled(failure);
          else problem.show(failure);
        },
      },
    );
  };
  const title = draft.kind === 'note' ? t('conversation.add_note') : t(`reply_mode.${draft.mode}`);
  return (
    <Card
      size="small"
      title={title}
      data-testid="conv-composer"
      data-kind={kind}
      styles={{ body: { display: 'flex', flexDirection: 'column', gap: 8 } }}
    >
      {draft.kind === 'reply' && (
        <>
          <Select
            mode="tags"
            aria-label={t('conversation.to')}
            prefix={`${t('conversation.to')}:`}
            value={to}
            onChange={setTo}
            tokenSeparators={[',', ';', ' ']}
            open={false}
            suffixIcon={null}
            status={fieldErrors.some((f) => f.field === 'body.to') ? 'error' : undefined}
            data-testid="conv-to"
          />
          <Select
            mode="tags"
            aria-label={t('conversation.cc')}
            prefix={`${t('conversation.cc')}:`}
            value={cc}
            onChange={setCc}
            tokenSeparators={[',', ';', ' ']}
            open={false}
            suffixIcon={null}
            status={fieldErrors.some((f) => f.field === 'body.cc') ? 'error' : undefined}
            data-testid="conv-cc"
          />
          <Alert type="info" showIcon message={t('conversation.email_not_configured_hint')} />
        </>
      )}
      {draft.kind === 'note' && (
        <Radio.Group
          value={visibility}
          onChange={(event) => {
            setVisibility(event.target.value as Visibility);
          }}
          aria-label={t('conversation.visibility')}
          data-testid="conv-visibility"
        >
          <Radio value="private" data-testid="conv-visibility-private">
            <LockOutlined /> {t('conversation.kind.private_note')} —{' '}
            {t('conversation.private_hint')}
          </Radio>
          <Radio
            value="public"
            disabled={item.conversation_actions.find((a) => a.action === 'reply')?.allowed !== true}
            data-testid="conv-visibility-public"
          >
            <GlobalOutlined /> {t('conversation.kind.public_note')} —{' '}
            {t('conversation.public_hint')}
          </Radio>
        </Radio.Group>
      )}
      <RichTextField
        label={title}
        value={body}
        onChange={(html) => {
          setBody(html);
          typed();
        }}
        placeholder={t(
          draft.kind === 'note'
            ? 'conversation.note_placeholder'
            : 'conversation.reply_placeholder',
        )}
        mentions={mentions}
        templates={templates.data}
        onManageTemplates={
          can('settings.manage')
            ? () => {
                // A new tab, so this draft stays; the list here reloads live when saved there.
                window.open(REPLY_TEMPLATES_SETTINGS, '_blank', 'noopener');
              }
            : undefined
        }
        minHeight={180}
        autoFocus
        invalid={fieldErrors.some((f) => f.field === 'body.body')}
        testId="conv-editor"
        imageOwnerId={me}
      />
      <Attachments
        files={drafts}
        target={me === undefined ? null : { ownerType: 'draft', ownerId: me }}
        onStored={(file) => {
          setDraftIds((ids) => [...ids, file.id]);
        }}
        onRemoved={(file) => {
          setDraftIds((ids) => ids.filter((id) => id !== file.id));
        }}
        canRemove
        staffOnly={kind === 'note' && visibility === 'private'}
        compact
        testId="conv-attachments"
      />
      {error !== null && error.status === 422 && (
        <Alert
          type="error"
          showIcon
          data-testid="conv-errors"
          message={describeError(error, t).title}
          description={
            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
              {fieldErrors.map((f) => (
                <li key={`${f.field}-${f.code}`}>
                  {t(`conversation.field.${f.field.replace('body.', '')}`)}:{' '}
                  {t(f.message_key, f.params ?? {})}
                </li>
              ))}
            </ul>
          }
        />
      )}
      <FormProblem problem={problem} />
      <Flex justify="end" gap={8}>
        <Button
          onClick={() => {
            stopTyping();
            onDone();
          }}
          data-testid="conv-cancel"
        >
          {t('actions.cancel')}
        </Button>
        <WriteButton
          type="primary"
          loading={add.isPending}
          disabled={body === ''}
          onClick={() => {
            send();
          }}
          data-testid="conv-send"
        >
          {t(draft.kind === 'note' ? 'conversation.save_note' : 'conversation.send')}
        </WriteButton>
      </Flex>
      <Modal
        open={unseen !== null}
        title={t('conversation.mention_warning_title')}
        footer={null}
        onCancel={() => {
          setUnseen(null);
        }}
        destroyOnHidden
      >
        <div data-testid="conv-mention-warning">
          {(unseen ?? []).map((name) => (
            <Typography.Paragraph key={name} style={{ marginBottom: 4 }}>
              {t('conversation.mention_cannot_see', { name })}
            </Typography.Paragraph>
          ))}
          <ModalButtons
            onSend={() => {
              send(true);
            }}
            onBack={() => {
              setUnseen(null);
            }}
          />
        </div>
      </Modal>
    </Card>
  );
}

/** Names of mentioned people the composer was told cannot see the incident (D-081). */
function cannotSee(html: string): string[] {
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
  return [...doc.querySelectorAll('span[data-type="mention"][data-can-see="false"]')].map(
    (span) => span.getAttribute('data-label') ?? span.textContent.replace(/^@/, ''),
  );
}

/** The editor's composer-only marks (who cannot see) are not sent; the server keeps none. */
function withoutComposerMarkers(html: string): string {
  return html.replace(/\sdata-can-see="(?:true|false)"/g, '');
}

function ModalButtons({ onSend, onBack }: { onSend: () => void; onBack: () => void }) {
  const t = useLabel();
  return (
    <Flex justify="end" gap={8} style={{ marginTop: 12 }}>
      <Button onClick={onBack}>{t('conversation.go_back')}</Button>
      <Button type="primary" onClick={onSend}>
        {t('conversation.send_anyway')}
      </Button>
    </Flex>
  );
}
