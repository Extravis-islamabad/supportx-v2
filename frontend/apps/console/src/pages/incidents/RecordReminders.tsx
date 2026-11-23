import { DeleteOutlined } from '@ant-design/icons';
import { Button, Card, Checkbox, Flex, Input, List, Select, Typography } from 'antd';
import { useState, type ReactNode } from 'react';

import {
  useRecordReminders,
  useReminderChange,
  type ChecklistBase,
  type Reminder,
} from '@supportx/api-client';
import {
  DateTimeField,
  EmptyText,
  lengthLimit,
  reportError,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { ALERT_CHOICES, useRemindersLive } from './remindersLive';

// Your own reminders on this record (WP-046a S2; REQ-INC-082): only yours, never anyone else's,
// administrators included. They change live on your personal channel only
// (`work_items.my_reminders_changed`), so two of your windows agree and nobody else hears.

const NOTE_MAX = 1000;
export function RecordReminders({
  recordId,
  base = 'incidents',
}: {
  recordId: string;
  base?: ChecklistBase;
}) {
  const t = useLabel();
  const found = useRecordReminders(recordId, base);
  const change = useReminderChange();
  const [note, setNote] = useState('');
  const [at, setAt] = useState<string | null>(null);
  const [alert, setAlert] = useState<number>(0);
  useRemindersLive();
  const add = () => {
    if (at === null) return;
    change.mutate(
      {
        kind: 'add',
        recordId,
        base,
        body: { note: note.trim(), remind_at: at, alert_minutes: alert },
      },
      {
        onSuccess: () => {
          setNote('');
          setAt(null);
          setAlert(0);
        },
        onError: reportError,
      },
    );
  };
  const rows = found.data ?? [];
  return (
    <Card size="small" title={t('reminders.title')} data-testid="record-reminders">
      <List
        size="small"
        loading={found.isPending}
        dataSource={rows}
        locale={{ emptyText: <EmptyText>{t('reminders.none')}</EmptyText> }}
        renderItem={(reminder) => <ReminderRow reminder={reminder} />}
      />
      <Flex vertical gap={8} style={{ marginTop: 8 }} data-testid="reminder-add">
        <Input
          value={note}
          count={lengthLimit(NOTE_MAX)}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          placeholder={t('reminders.note_placeholder')}
          aria-label={t('reminders.note_placeholder')}
          data-testid="reminder-note"
        />
        <DateTimeField value={at} onChange={setAt} testId="reminder-at" />
        <Select
          value={alert}
          onChange={setAlert}
          aria-label={t('reminders.alert')}
          data-testid="reminder-alert"
          options={ALERT_CHOICES.map((minutes) => ({
            value: minutes,
            label: t(`reminders.alert_before.${String(minutes)}`),
          }))}
        />
        <WriteButton
          onClick={add}
          loading={change.isPending}
          disabled={note.trim() === '' || at === null}
          whyDisabled={t('reminders.why.note_and_time')}
          data-testid="reminder-add-button"
        >
          {t('reminders.add')}
        </WriteButton>
      </Flex>
    </Card>
  );
}

export function ReminderRow({
  reminder,
  heading,
}: {
  reminder: Reminder;
  /** Above the note: the record it is on (the header drawer). */
  heading?: ReactNode;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const change = useReminderChange();
  const done = reminder.done_at !== null;
  return (
    <List.Item
      data-testid={`reminder-${reminder.id}`}
      actions={[
        <Button
          key="delete"
          size="small"
          type="text"
          icon={<DeleteOutlined />}
          aria-label={t('reminders.delete_named', { note: reminder.note })}
          onClick={() => {
            change.mutate(
              { kind: 'delete', reminderId: reminder.id, version: reminder.version },
              { onError: reportError },
            );
          }}
        />,
      ]}
    >
      <Checkbox
        checked={done}
        aria-label={t(done ? 'reminders.reopen' : 'reminders.mark_done')}
        onChange={(e) => {
          change.mutate(
            {
              kind: 'update',
              reminderId: reminder.id,
              version: reminder.version,
              body: { done: e.target.checked },
            },
            { onError: reportError },
          );
        }}
      >
        <Flex vertical>
          {heading}
          <Typography.Text delete={done}>{reminder.note}</Typography.Text>
          <Typography.Text type="secondary">{dates.format(reminder.remind_at)}</Typography.Text>
        </Flex>
      </Checkbox>
    </List.Item>
  );
}
