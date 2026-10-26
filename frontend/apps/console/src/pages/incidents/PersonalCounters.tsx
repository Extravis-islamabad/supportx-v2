import { Button, Flex, theme } from 'antd';

import { useIncidentCounters } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

import { COUNTERS } from './counters';

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
  const counters = useIncidentCounters();
  const found = new Map((counters.data ?? []).map((c) => [c.counter, c]));
  return (
    <Flex gap={8} wrap role="group" aria-label={t('counters.title')} data-testid="inc-counters">
      {COUNTERS.map((code) => {
        const counter = found.get(code);
        const count =
          counter === undefined ? '–' : `${String(counter.count)}${counter.capped ? '+' : ''}`;
        const warn = code === 'my_overdue' && (counter?.count ?? 0) > 0;
        return (
          <Button
            key={code}
            type={active === code ? 'primary' : 'default'}
            onClick={() => {
              onOpen(code);
            }}
            aria-pressed={active === code}
            data-testid={`inc-counter-${code}`}
            style={{ height: 'auto', paddingBlock: 6 }}
          >
            <Flex vertical align="start">
              <span
                style={{
                  fontWeight: 600,
                  fontSize: token.fontSizeLG,
                  color: active !== code && warn ? token.colorError : undefined,
                }}
                data-testid={`inc-counter-${code}-count`}
              >
                {count}
              </span>
              <span>{t(`work_item_view.${code}`)}</span>
            </Flex>
          </Button>
        );
      })}
    </Flex>
  );
}
