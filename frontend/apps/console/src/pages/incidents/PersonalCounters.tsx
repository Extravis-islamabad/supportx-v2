import {
  ClockCircleOutlined,
  SyncOutlined,
  UserAddOutlined,
  UserOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { theme } from 'antd';
import type { ReactNode } from 'react';

import { useIncidentCounters } from '@supportx/api-client';
import { useAppearance, useLabel, useMinWidth } from '@supportx/ui';

import { COUNTERS } from './counters';

// Each counter's icon and tint (the design target). Measured on the tints: #B42318 5.5:1,
// #B54708 4.8:1, #175CD3 5.6:1, #067647 5.4:1, #6B33B8 6.5:1.
const LOOKS: Record<(typeof COUNTERS)[number], { icon: ReactNode; bg: string; fg: string }> = {
  my_overdue: { icon: <WarningOutlined />, bg: '#FEE4E2', fg: '#B42318' },
  my_due_today: { icon: <ClockCircleOutlined />, bg: '#FEF0C7', fg: '#B54708' },
  waiting_on_me: { icon: <UserOutlined />, bg: '#EFF8FF', fg: '#175CD3' },
  updated_by_others: { icon: <SyncOutlined />, bg: '#ECFDF3', fg: '#067647' },
  unassigned_in_my_groups: { icon: <UserAddOutlined />, bg: '#F4EBFF', fg: '#6B33B8' },
};

/**
 * Personal counters (REQ-INC-128): live (the list channel refreshes them; overdue and due today
 * also every minute). Each opens the view of the same name, which lists exactly the counted
 * records. "Pending my approval" comes with approvals (WP-030).
 */
export function PersonalCounters({
  active,
  onOpen,
}: {
  active: string;
  onOpen: (view: string) => void;
}) {
  const t = useLabel();
  const { token } = theme.useToken();
  const { mode } = useAppearance();
  const counters = useIncidentCounters();
  const wide = useMinWidth(576);
  const found = new Map((counters.data ?? []).map((c) => [c.counter, c]));
  return (
    <div
      role="group"
      aria-label={t('counters.title')}
      data-testid="inc-counters"
      style={
        wide
          ? {
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
              gap: 12,
            }
          : // A phone: one row that scrolls sideways (QA10V-26: five tiles stacked to ~430 px
            // before the list began).
            {
              display: 'grid',
              gridAutoFlow: 'column',
              gridAutoColumns: 'minmax(140px, 1fr)',
              gap: 8,
              overflowX: 'auto',
              paddingBlockEnd: 4,
            }
      }
    >
      {COUNTERS.map((code) => {
        const counter = found.get(code);
        const count =
          counter === undefined ? '–' : `${String(counter.count)}${counter.capped ? '+' : ''}`;
        const warn = code === 'my_overdue' && (counter?.count ?? 0) > 0;
        // The tints are for light surfaces; dark keeps the theme's own colours (lane A's review).
        const look =
          mode === 'dark'
            ? {
                ...LOOKS[code],
                bg: token.colorFillSecondary,
                fg: code === 'my_overdue' ? token.colorError : token.colorTextSecondary,
              }
            : LOOKS[code];
        const on = active === code;
        return (
          // A tile (UI pass 2): the icon on its tint, the number large, the view's name below.
          <button
            key={code}
            type="button"
            onClick={() => {
              onOpen(code);
            }}
            aria-pressed={on}
            data-testid={`inc-counter-${code}`}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: wide ? '12px 14px' : '8px 10px',
              textAlign: 'start',
              font: 'inherit',
              color: token.colorText,
              cursor: 'pointer',
              background: on ? token.colorPrimaryBg : token.colorBgContainer,
              border: `1px solid ${on ? token.colorPrimary : warn ? '#FECDCA' : token.colorBorderSecondary}`,
              borderRadius: token.borderRadius,
            }}
          >
            <span
              aria-hidden
              style={{
                width: 36,
                height: 36,
                flexShrink: 0,
                borderRadius: 8,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: look.bg,
                color: look.fg,
                fontSize: 18,
              }}
            >
              {look.icon}
            </span>
            <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
              <span
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  lineHeight: 1.1,
                  color: !on && warn ? token.colorError : undefined,
                }}
                data-testid={`inc-counter-${code}-count`}
              >
                {count}
              </span>
              <span style={{ fontSize: 12, fontWeight: 500, color: token.colorTextSecondary }}>
                {t(`work_item_view.${code}`)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
