import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import {
  isApiError,
  queryKeys,
  useAddConversationEntry,
  useIncident,
  useIncidentAction,
  useIncidentConversation,
  useTakeIncident,
  type components,
} from '@supportx/api-client';
import { useLabels } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';

import { Button } from '../components/Button';
import { Screen } from '../components/Screen';
import { useMe } from '../session';
import { slaView, useNow } from '../sla';
import { SPACE, usePalette } from '../theme';
import { priorityTone, statusCategoryTone, TONES } from '../tones';
import { Card, Chip, Field, Heading, Muted, Row, Sheet, useToast } from '../ui';
import { personName } from './parts';

type ActionState = components['schemas']['WorkItemActionStateOut'];

/** The three actions of the prototype, always in this order (disabled ones say why). */
const ACTIONS = ['take', 'start_work', 'resolve'] as const;
type Action = (typeof ACTIONS)[number];

function newKey(): string {
  return crypto.randomUUID();
}

export function IncidentScreen({ id }: { id: string }) {
  const t = useLabels();
  const palette = usePalette();
  const queryClient = useQueryClient();
  const show = useToast((state) => state.show);
  const me = useMe();
  const incident = useIncident(id);
  const conversation = useIncidentConversation(id);
  const take = useTakeIncident(id);
  const act = useIncidentAction(id);
  const add = useAddConversationEntry(id);
  const now = useNow();
  const [mode, setMode] = useState<'reply' | 'note'>('reply');
  const [draft, setDraft] = useState('');
  const [draftKey, setDraftKey] = useState(newKey);
  const [resolving, setResolving] = useState(false);
  const [resolution, setResolution] = useState('');
  const [resolutionError, setResolutionError] = useState(false);
  // Someone else's change appears without a refresh (rule 5c).
  useRecordChannel('wi', id, () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.detail(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.conversation(id) });
  });

  const item = incident.data;
  if (item === undefined) {
    return (
      <Screen title={t('mobile.incident.title')}>
        {incident.isError ? (
          <Muted testID="incident-missing" text={t('errors.not_found')} />
        ) : (
          <ActivityIndicator color={palette.primary} />
        )}
      </Screen>
    );
  }

  const fail = (error: unknown) => {
    show(t(isApiError(error) ? error.messageKey : 'errors.internal_error'));
  };
  const state = (action: Exclude<Action, 'take'>): ActionState | undefined =>
    item.actions.find((a) => a.action === action);
  const canTake =
    item.technician_id === null &&
    (item.status_category === 'open' || item.status_category === 'paused');
  const enabled: Record<Action, boolean> = {
    take: canTake,
    start_work: state('start_work')?.allowed === true,
    resolve: state('resolve')?.allowed === true,
  };
  const primary: Action | undefined = ACTIONS.find((a) => enabled[a]);
  const reasonOf = (action: Action): string | null => {
    if (action === 'take') {
      if (canTake) return null;
      return item.technician_id === me.data?.user.id
        ? 'action_reason.already_yours'
        : 'action_reason.assigned_to_other';
    }
    const reason = state(action)?.reason;
    return reason ? `action_reason.${reason}` : null;
  };
  const hint =
    item.status_category === 'resolved'
      ? t('mobile.incident.hint_resolved')
      : primary !== undefined
        ? t(`mobile.incident.hint_${primary}`)
        : (() => {
            const reason = reasonOf('resolve') ?? reasonOf('start_work');
            return reason === null ? '' : t(reason);
          })();

  const run = (action: Action) => {
    if (action === 'resolve') {
      setResolution('');
      setResolutionError(false);
      setResolving(true);
      return;
    }
    const done = () => {
      show(t(`mobile.toast.${action}`, { id: item.display_id }));
    };
    if (action === 'take')
      take.mutate({ version: item.version }, { onSuccess: done, onError: fail });
    else act.mutate({ action, version: item.version }, { onSuccess: done, onError: fail });
  };

  const confirmResolve = () => {
    const text = resolution.trim();
    if (text === '') {
      setResolutionError(true);
      return;
    }
    act.mutate(
      { action: 'resolve', version: item.version, resolution: text },
      {
        onSuccess: () => {
          setResolving(false);
          show(t('mobile.toast.resolve', { id: item.display_id }));
        },
        onError: fail,
      },
    );
  };

  const send = () => {
    const body = draft.trim();
    if (body === '') return;
    add.mutate(
      {
        body: { kind: mode, body, visibility: mode === 'note' ? 'private' : 'public' },
        key: draftKey,
      },
      {
        onSuccess: () => {
          setDraft('');
          setDraftKey(newKey());
          show(t(mode === 'reply' ? 'mobile.toast.reply' : 'mobile.toast.note'));
        },
        onError: fail,
      },
    );
  };

  const sla = slaView(t, now, item);
  const people = item.people as Record<string, components['schemas']['PersonOut']>;
  const entries = conversation.data?.items ?? [];
  const talkers = conversation.data?.people;
  const busy = take.isPending || act.isPending;
  const noteTint = { bg: '#FFFAEB', border: '#FEDF89' };

  return (
    <Screen
      title={item.display_id}
      aside={
        <Button
          variant="plain"
          title={t('mobile.back')}
          onPress={() => {
            if (router.canGoBack()) router.back();
            else router.replace('/t/queue');
          }}
        />
      }
    >
      <Card>
        <Row>
          <Chip text={t(`priority.${item.priority}`)} tone={priorityTone(item.priority)} />
          <Chip
            testID="incident-status"
            text={t(`work_item_status.${item.status}`)}
            tone={statusCategoryTone(item.status_category)}
          />
        </Row>
        <Text style={[styles.subject, { color: palette.text }]}>{item.subject}</Text>
        <View style={styles.people}>
          <View style={styles.cell}>
            <Text style={[styles.small, { color: palette.textSecondary }]}>
              {t('mobile.incident.requester')}
            </Text>
            <Text style={[styles.strong, { color: palette.text }]}>
              {personName(people, item.requester_id) ?? ''}
            </Text>
          </View>
          <View style={styles.cell}>
            <Text style={[styles.small, { color: palette.textSecondary }]}>
              {t('mobile.incident.assignee')}
            </Text>
            <Text testID="incident-assignee" style={[styles.strong, { color: palette.text }]}>
              {item.technician_id === null
                ? t('work_item_view.unassigned')
                : item.technician_id === me.data?.user.id
                  ? t('mobile.you')
                  : (personName(people, item.technician_id) ?? '')}
            </Text>
          </View>
        </View>
        <View style={[styles.sla, { backgroundColor: sla.tone.bg }]}>
          <Text testID="incident-sla" style={{ color: sla.tone.fg, fontWeight: '600' }}>
            {sla.text}
          </Text>
        </View>
        <View style={styles.actions}>
          {ACTIONS.map((action) => {
            const on = enabled[action] && !busy;
            const main = action === primary;
            const why = reasonOf(action);
            return (
              <Pressable
                key={action}
                testID={`action-${action}`}
                accessibilityRole="button"
                accessibilityState={{ disabled: !on }}
                accessibilityHint={on || why === null ? undefined : t(why)}
                disabled={!on}
                onPress={() => {
                  run(action);
                }}
                style={[
                  styles.action,
                  {
                    backgroundColor: !on
                      ? palette.muted
                      : main
                        ? palette.primary
                        : palette.background,
                    borderColor: !on
                      ? palette.border
                      : main
                        ? palette.primary
                        : palette.strongBorder,
                  },
                ]}
              >
                <Text
                  style={[
                    styles.actionText,
                    {
                      color: !on ? palette.textSecondary : main ? palette.onPrimary : palette.text,
                    },
                  ]}
                >
                  {t(action === 'take' ? 'mobile.incident.take' : `work_item_action.${action}`)}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Muted testID="incident-hint" text={hint} />
      </Card>

      <Heading text={t('mobile.incident.conversation')} />
      {entries.map((entry) => {
        const note = entry.kind === 'note';
        return (
          <Card
            key={entry.id}
            style={
              note ? { backgroundColor: noteTint.bg, borderColor: noteTint.border } : undefined
            }
          >
            <View style={styles.entryHead}>
              <Text style={[styles.strong, { color: '#1B1530' }]}>
                {entry.automatic
                  ? t('mobile.incident.system')
                  : (personName(talkers, entry.created_by) ?? '')}
              </Text>
              <Text style={[styles.small, { color: '#57516B' }]}>
                {new Date(entry.created_at).toLocaleString()}
              </Text>
            </View>
            <Text style={[styles.kind, { color: note ? TONES.warning.fg : TONES.info.fg }]}>
              {t(note ? 'mobile.incident.note_kind' : 'mobile.incident.reply_kind')}
            </Text>
            <Text style={{ color: '#1B1530', fontSize: 14, lineHeight: 20 }}>{entry.body}</Text>
          </Card>
        );
      })}
      {entries.length === 0 && !conversation.isPending ? (
        <Muted text={t('mobile.incident.no_conversation')} />
      ) : null}

      <Card>
        <View
          accessibilityRole="tablist"
          style={[styles.segment, { backgroundColor: palette.muted }]}
        >
          {(['reply', 'note'] as const).map((kind) => {
            const on = mode === kind;
            return (
              <Pressable
                key={kind}
                testID={`mode-${kind}`}
                accessibilityRole="tab"
                accessibilityState={{ selected: on }}
                onPress={() => {
                  setMode(kind);
                }}
                style={[styles.segmentItem, on && { backgroundColor: palette.background }]}
              >
                <Text
                  style={{
                    fontWeight: '600',
                    color: on
                      ? kind === 'note'
                        ? TONES.warning.fg
                        : TONES.info.fg
                      : palette.textSecondary,
                  }}
                >
                  {t(kind === 'reply' ? 'mobile.incident.reply' : 'mobile.incident.note')}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Field
          testID="composer"
          label={t(mode === 'reply' ? 'mobile.incident.reply_hint' : 'mobile.incident.note_hint')}
          value={draft}
          onChange={setDraft}
          placeholder={t(
            mode === 'reply'
              ? 'mobile.incident.reply_placeholder'
              : 'mobile.incident.note_placeholder',
          )}
          tint={mode === 'note' ? noteTint : undefined}
        />
        <Button
          testID="send"
          title={t('mobile.incident.send')}
          busy={add.isPending}
          onPress={send}
        />
      </Card>

      <Sheet
        visible={resolving}
        title={t('mobile.incident.resolve_title')}
        onClose={() => {
          setResolving(false);
        }}
      >
        <Field
          testID="resolution"
          label={`${t('mobile.incident.resolution')} *`}
          value={resolution}
          onChange={(text) => {
            setResolution(text);
            setResolutionError(false);
          }}
          lines={4}
          error={resolutionError ? t('mobile.incident.resolution_required') : null}
        />
        <View style={styles.sheetButtons}>
          <View style={styles.flex}>
            <Button
              variant="plain"
              title={t('mobile.cancel')}
              onPress={() => {
                setResolving(false);
              }}
            />
          </View>
          <View style={styles.flex}>
            <Button
              testID="confirm-resolve"
              title={t('work_item_action.resolve')}
              busy={act.isPending}
              onPress={confirmResolve}
            />
          </View>
        </View>
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  subject: { fontSize: 19, fontWeight: '700', lineHeight: 25 },
  people: { flexDirection: 'row', gap: SPACE.sm },
  cell: { flex: 1, gap: 2 },
  small: { fontSize: 12 },
  strong: { fontSize: 13, fontWeight: '600' },
  sla: { borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 },
  actions: { flexDirection: 'row', gap: SPACE.sm },
  action: {
    flex: 1,
    minHeight: 44,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  actionText: { fontSize: 14, fontWeight: '600', textAlign: 'center' },
  entryHead: { flexDirection: 'row', justifyContent: 'space-between', gap: SPACE.sm },
  kind: { fontSize: 11, fontWeight: '700' },
  segment: { flexDirection: 'row', borderRadius: 12, padding: 4, gap: 6 },
  segmentItem: {
    flex: 1,
    minHeight: 36,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sheetButtons: { flexDirection: 'row', gap: SPACE.sm },
  flex: { flex: 1 },
});
