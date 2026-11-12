import { ClockCircleOutlined } from '@ant-design/icons';
import { Badge, Button, Drawer, List, Tooltip, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import { useMyReminders, type MyReminder } from '@supportx/api-client';
import { EmptyText, useLabel } from '@supportx/ui';

import { ReminderRow } from './RecordReminders';
import { useRemindersLive } from './remindersLive';

// Your open reminders on every record, in the header (WP-046a S2; REQ-INC-082 AC2), soonest
// first. A record you can no longer see stays listed as "no longer available", with no number
// or subject (the coordinator's rule): you may still finish or remove the reminder there.

const RECORD_PATHS: Record<string, string> = {
  incident: 'incidents',
  problem: 'problems',
  change: 'changes',
};

export function RemindersDrawer() {
  const t = useLabel();
  const [open, setOpen] = useState(false);
  const mine = useMyReminders(true);
  useRemindersLive();
  const rows = [...(mine.data ?? [])].sort((a, b) => a.remind_at.localeCompare(b.remind_at));
  const now = new Date().toISOString();
  const due = rows.filter((r) => r.remind_at <= now).length;
  const label = t('reminders.mine_count', { count: rows.length, due });
  const recordLink = (r: MyReminder) => {
    const base = RECORD_PATHS[r.record_type];
    if (!r.available || base === undefined || r.display_id == null) {
      return <Typography.Text type="secondary">{t('reminders.unavailable')}</Typography.Text>;
    }
    return (
      <Link
        to={`/${base}/${r.work_item_id}`}
        onClick={() => {
          setOpen(false);
        }}
      >
        {`${r.display_id} · ${r.subject ?? ''}`}
      </Link>
    );
  };
  return (
    <>
      <Tooltip title={label}>
        <Badge count={due} overflowCount={99} offset={[-2, 2]}>
          <Button
            type="text"
            icon={<ClockCircleOutlined />}
            aria-label={label}
            onClick={() => {
              setOpen(true);
            }}
            data-testid="reminders-drawer-open"
          />
        </Badge>
      </Tooltip>
      <Drawer
        open={open}
        title={t('reminders.mine')}
        onClose={() => {
          setOpen(false);
        }}
        data-testid="reminders-drawer"
      >
        <List
          dataSource={rows}
          loading={mine.isPending}
          locale={{ emptyText: <EmptyText>{t('reminders.mine_none')}</EmptyText> }}
          renderItem={(r) => <ReminderRow key={r.id} reminder={r} heading={recordLink(r)} />}
        />
      </Drawer>
    </>
  );
}
