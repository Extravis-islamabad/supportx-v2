import { BulbOutlined } from '@ant-design/icons';
import { Flex, Typography } from 'antd';
import { Link } from 'react-router';

import type { CausingProblem } from '@supportx/api-client';
import { RichTextView, ToneTag, useDateTime, useLabel } from '@supportx/ui';

import { StatusTag } from './tags';

/**
 * The problem causing this incident, as incident technicians see it (WP-044c D14, REQ-PRB-071):
 * what it is and where it stands, whether it is a known error, what to do meanwhile and when it
 * should be solved. Never its root cause (Q7). Its ID opens it for those who may see problems.
 */
export function CausingProblemCard({ cause }: { cause: CausingProblem }) {
  const t = useLabel();
  const dates = useDateTime();
  return (
    <Flex vertical gap={8} data-testid="inc-causing-problem">
      <Flex gap={8} wrap align="center">
        {cause.may_open ? (
          <Link to={`/problems/${cause.id}`} data-testid="inc-causing-problem-open">
            <strong dir="ltr">{cause.display_id}</strong>
          </Link>
        ) : (
          <strong dir="ltr">{cause.display_id}</strong>
        )}
        {/* The problem's statuses are named without its settings (no problem rights needed). */}
        <StatusTag status={cause.status} catalogue={undefined} />
        {cause.known_error && (
          <ToneTag tone="warning" icon={<BulbOutlined />} testId="inc-causing-known-error">
            {t('problems.known_error.tag')}
          </ToneTag>
        )}
      </Flex>
      <bdi dir="auto">{cause.subject}</bdi>
      {cause.workaround != null && cause.workaround !== '' && (
        <Flex vertical gap={2}>
          <Typography.Text type="secondary">{t('work_item.field.workaround')}</Typography.Text>
          <RichTextView html={cause.workaround} />
        </Flex>
      )}
      {cause.target_at != null && (
        <Typography.Text type="secondary" data-testid="inc-causing-target">
          {t('incidents.causing_problem.target', { date: dates.format(cause.target_at) })}
        </Typography.Text>
      )}
    </Flex>
  );
}
