import { useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Card, Flex, List, Modal, Typography } from 'antd';
import { useState } from 'react';

import {
  findMentionable,
  queryKeys,
  useAssetNoteActions,
  useAssetNoteHistory,
  useAssetNotes,
  useRecordFiles,
  useUser,
  type AssetNote,
  type AssetRecord,
} from '@supportx/api-client';
import {
  Attachments,
  EmptyText,
  RichTextField,
  RichTextView,
  RowActions,
  useAccess,
  useDateTime,
  useLabel,
  useLicence,
  WriteButton,
  type MentionSearch,
} from '@supportx/ui';

import { problemText } from './problemText';

/** Staff to @mention; the server says afterwards who could not see the asset (not told). */
const mentions: MentionSearch = (query) =>
  findMentionable(query).then((people) =>
    people.map((p) => ({ id: p.id, label: p.display_name, email: p.email ?? '', canSee: true })),
  );

function PersonName({ id }: { id: string }) {
  const t = useLabel();
  const user = useUser(id);
  return <bdi dir="auto">{user.data?.display_name ?? t('audit.ui.erased_person')}</bdi>;
}

/** Who a mention did not reach: they cannot see the asset (REQ-INC-063 AC2). */
function NotTold({ people, onClose }: { people: string[]; onClose: () => void }) {
  const t = useLabel();
  return (
    <Alert
      type="warning"
      showIcon
      closable
      onClose={onClose}
      message={
        <span data-testid="asset-note-not-told">
          {t('assets.notes.not_told', { count: people.length })}{' '}
          {people.map((id, index) => (
            <span key={id}>
              {index > 0 && t('assets.notes.list_separator')}
              <PersonName id={id} />
            </span>
          ))}
        </span>
      }
    />
  );
}

/** A note's earlier texts (REQ-INC-062 AC1), newest first. */
function NoteVersions({
  assetId,
  noteId,
  onClose,
}: {
  assetId: string;
  noteId: string;
  onClose: () => void;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const versions = useAssetNoteHistory(assetId, noteId);
  return (
    <Modal
      open
      title={t('assets.notes.versions')}
      onCancel={onClose}
      footer={null}
      data-testid="asset-note-versions"
    >
      <List
        loading={versions.isPending}
        dataSource={(versions.data ?? []).filter((v) => v.body !== null)}
        renderItem={(v) => (
          <List.Item key={v.version}>
            <Flex vertical gap={4} style={{ width: '100%' }}>
              <Typography.Text type="secondary">
                {dates.format(v.occurred_at)}
                {' · '}
                <bdi dir="auto">{v.actor_name ?? t('assets.record.someone')}</bdi>
              </Typography.Text>
              <RichTextView html={v.body} />
            </Flex>
          </List.Item>
        )}
      />
    </Modal>
  );
}

function NoteItem({
  asset,
  note,
  onProblem,
  onNotTold,
}: {
  asset: AssetRecord;
  note: AssetNote;
  onProblem: (text: string | null) => void;
  onNotTold: (people: string[]) => void;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const { edit, remove } = useAssetNoteActions(asset.id);
  const [editing, setEditing] = useState<string | null>(null);
  const [versions, setVersions] = useState(false);
  const { modal } = App.useApp();
  const { writable } = useLicence();
  // Read-only mode: the note's actions stay, disabled, saying why (D-155).
  const readOnly = writable ? undefined : t('licence.read_only_action');
  const confirmDelete = () => {
    modal.confirm({
      title: t('assets.notes.delete_confirm'),
      okText: t('actions.delete'),
      okButtonProps: { danger: true, 'data-testid': 'asset-note-delete-confirm' },
      cancelText: t('actions.cancel'),
      onOk: () => {
        onProblem(null);
        remove.mutate(
          { id: note.id, version: note.version },
          {
            onError: (error) => {
              onProblem(problemText(t, error));
            },
          },
        );
      },
    });
  };
  if (note.deleted_at !== null) {
    return (
      <List.Item key={note.id} data-testid={`asset-note-${note.id}`}>
        <Typography.Text type="secondary" italic data-testid="asset-note-deleted">
          {t('assets.notes.deleted', {
            name: note.deleted_by_name ?? t('assets.record.someone'),
            date: dates.format(note.deleted_at),
          })}
        </Typography.Text>
      </List.Item>
    );
  }
  return (
    <List.Item key={note.id} data-testid={`asset-note-${note.id}`}>
      <Flex vertical gap={6} style={{ width: '100%', minWidth: 0 }}>
        <Flex gap={8} wrap align="center" justify="space-between">
          <Typography.Text type="secondary">
            <bdi dir="auto">{note.author_name ?? t('assets.record.someone')}</bdi>
            {' · '}
            {dates.format(note.created_at)}
            {note.edited_at !== null && (
              <>
                {' · '}
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, height: 'auto' }}
                  onClick={() => {
                    setVersions(true);
                  }}
                  data-testid="asset-note-edited"
                >
                  {t('assets.notes.edited')}
                </Button>
              </>
            )}
          </Typography.Text>
          {note.may_change && editing === null && (
            <RowActions
              rowName={t('assets.notes.row', {
                name: note.author_name ?? t('assets.record.someone'),
                date: dates.format(note.created_at),
              })}
              primary={{
                key: 'edit',
                label: t('actions.edit'),
                disabled: !writable,
                whyNot: readOnly,
                onClick: () => {
                  setEditing(note.body ?? '');
                },
                testId: `asset-note-edit-${note.id}`,
              }}
              more={[
                {
                  key: 'delete',
                  label: t('actions.delete'),
                  danger: true,
                  disabled: !writable,
                  whyNot: readOnly,
                  onClick: confirmDelete,
                  testId: `asset-note-delete-${note.id}`,
                },
              ]}
            />
          )}
        </Flex>
        {editing === null ? (
          <RichTextView html={note.body} testId={`asset-note-body-${note.id}`} />
        ) : (
          <Flex vertical gap={8}>
            <RichTextField
              label={t('assets.notes.edit_label')}
              value={editing}
              onChange={setEditing}
              mentions={mentions}
              testId="asset-note-editor"
            />
            <Flex gap={8}>
              <WriteButton
                type="primary"
                size="small"
                loading={edit.isPending}
                onClick={() => {
                  onProblem(null);
                  edit.mutate(
                    { id: note.id, version: note.version, body: editing },
                    {
                      onSuccess: (saved) => {
                        setEditing(null);
                        const missed = saved.not_notified ?? [];
                        if (missed.length > 0) onNotTold(missed);
                      },
                      onError: (error) => {
                        onProblem(problemText(t, error));
                      },
                    },
                  );
                }}
                data-testid="asset-note-edit-save"
              >
                {t('actions.save')}
              </WriteButton>
              <Button
                size="small"
                onClick={() => {
                  setEditing(null);
                }}
              >
                {t('actions.cancel')}
              </Button>
            </Flex>
          </Flex>
        )}
      </Flex>
      {versions && (
        <NoteVersions
          assetId={asset.id}
          noteId={note.id}
          onClose={() => {
            setVersions(false);
          }}
        />
      )}
    </List.Item>
  );
}

/**
 * Notes and attachments on an asset (WP-049b s2; REQ-AST-050): repair notes, invoices. Notes
 * follow the incident rules: rich text, @mentions (people who cannot see the asset are not told,
 * and the author hears who), the author edits or deletes their own (others' with
 * `assets.manage`), an edit keeps the earlier text behind its "edited" marker, a deleted note
 * stays as a line saying who deleted it and when. Attachments are the asset's files through the
 * shared files service (scanned; an infected file is refused, as on incidents). Live: the asset's
 * channel names "notes", and file changes arrive as `files.changed`.
 */
export function AssetNotes({ asset, manage }: { asset: AssetRecord; manage: boolean }) {
  const t = useLabel();
  const { can } = useAccess();
  const queryClient = useQueryClient();
  const notes = useAssetNotes(asset.id);
  const { create } = useAssetNoteActions(asset.id);
  const files = useRecordFiles('asset', asset.id);
  const [draft, setDraft] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [problem, setProblem] = useState<string | null>(null);
  const [notTold, setNotTold] = useState<string[]>([]);
  const attachments = (files.data ?? []).filter((f) => f.owner_type === 'asset' && !f.inline);
  const add = () => {
    setProblem(null);
    create.mutate(
      { key, body: draft },
      {
        onSuccess: (saved) => {
          setDraft('');
          setKey(crypto.randomUUID());
          setNotTold(saved.not_notified ?? []);
        },
        onError: (error) => {
          setKey(crypto.randomUUID());
          setProblem(problemText(t, error));
        },
      },
    );
  };
  return (
    <Flex vertical gap={16} style={{ paddingBottom: 16 }} data-testid="asset-notes">
      <Card size="small" title={t('assets.notes.title')}>
        <Flex vertical gap={8}>
          {problem !== null && (
            <Alert
              type="error"
              showIcon
              closable
              message={problem}
              onClose={() => {
                setProblem(null);
              }}
            />
          )}
          {notTold.length > 0 && (
            <NotTold
              people={notTold}
              onClose={() => {
                setNotTold([]);
              }}
            />
          )}
          <RichTextField
            label={t('assets.notes.new_label')}
            placeholder={t('assets.notes.placeholder')}
            value={draft}
            onChange={setDraft}
            mentions={mentions}
            testId="asset-note-composer"
          />
          <Flex>
            <WriteButton
              loading={create.isPending}
              disabled={draft.replace(/<[^>]*>/g, '').trim() === ''}
              whyDisabled={t('assets.notes.empty')}
              onClick={add}
              data-testid="asset-note-add"
            >
              {t('assets.notes.add')}
            </WriteButton>
          </Flex>
          <List
            loading={notes.isPending}
            dataSource={notes.data ?? []}
            locale={{ emptyText: <EmptyText>{t('assets.notes.none')}</EmptyText> }}
            renderItem={(note) => (
              <NoteItem asset={asset} note={note} onProblem={setProblem} onNotTold={setNotTold} />
            )}
            data-testid="asset-notes-list"
          />
        </Flex>
      </Card>
      <Card size="small" title={t('assets.notes.attachments')} data-testid="asset-files">
        {attachments.length === 0 && !manage && <EmptyText>{t('files.empty')}</EmptyText>}
        <Attachments
          files={attachments}
          target={manage ? { ownerType: 'asset', ownerId: asset.id } : null}
          onStored={() => {
            void queryClient.invalidateQueries({
              queryKey: queryKeys.files.record('asset', asset.id),
            });
          }}
          canRemove={manage}
          canRescan={can('files.manage')}
          testId="asset-attachments"
        />
      </Card>
    </Flex>
  );
}
