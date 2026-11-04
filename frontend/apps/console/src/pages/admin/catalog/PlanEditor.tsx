import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { Button, Card, Checkbox, Flex, Input, Select, Typography } from 'antd';

import { useUnits, type CatalogItem } from '@supportx/api-client';
import { lengthLimit, useLabel } from '@supportx/ui';

type Task = CatalogItem['plan'][number];
const LANGUAGES = ['en', 'ar', 'ur'] as const;

/**
 * The fulfilment plan (WP-031 plan D9; REQ-SR-046): ordered tasks, each with its title per
 * language, a group of its own (or the item's), required or not, and internal (requesters see
 * only "step n of m"). The last required task done fulfils the request when auto-fulfil is on.
 */
export function PlanEditor({
  value,
  onChange,
  disabled,
}: {
  value: Task[];
  onChange: (next: Task[]) => void;
  disabled: boolean;
}) {
  const t = useLabel();
  const groups = useUnits('groups');
  const put = (index: number, next: Partial<Task>) => {
    onChange(value.map((task, i) => (i === index ? { ...task, ...next } : task)));
  };
  const move = (index: number, by: number) => {
    const next = [...value];
    const [moved] = next.splice(index, 1);
    if (moved === undefined) return;
    next.splice(index + by, 0, moved);
    onChange(next);
  };
  return (
    <Flex vertical gap={12} data-testid="cat-plan">
      {value.length === 0 && (
        <Typography.Text type="secondary">{t('catalog_admin.plan.none')}</Typography.Text>
      )}
      {value.map((task, index) => (
        <Card
          // The plan has no IDs: a task is its place in the list.
          key={index}
          size="small"
          title={t('catalog_admin.plan.task_n', { n: index + 1 })}
          data-testid={`cat-task-${String(index)}`}
          extra={
            <Flex gap={0}>
              <Button
                type="text"
                size="small"
                icon={<ArrowUpOutlined />}
                aria-label={t('catalog_admin.move_up')}
                disabled={disabled || index === 0}
                onClick={() => {
                  move(index, -1);
                }}
              />
              <Button
                type="text"
                size="small"
                icon={<ArrowDownOutlined />}
                aria-label={t('catalog_admin.move_down')}
                disabled={disabled || index === value.length - 1}
                onClick={() => {
                  move(index, 1);
                }}
              />
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                aria-label={t('catalog_admin.plan.remove')}
                disabled={disabled}
                onClick={() => {
                  onChange(value.filter((_, i) => i !== index));
                }}
              />
            </Flex>
          }
        >
          <Flex vertical gap={8}>
            <Flex gap={8} wrap>
              {LANGUAGES.map((lang) => (
                <Input
                  key={lang}
                  lang={lang}
                  dir={lang === 'en' ? 'ltr' : 'rtl'}
                  style={{ flex: '1 1 180px' }}
                  placeholder={t(`settings.name_in.${lang}`)}
                  aria-label={`${t('catalog_admin.plan.title')} (${t(`settings.name_in.${lang}`)})`}
                  count={lengthLimit(120)}
                  disabled={disabled}
                  value={task.title[lang] ?? ''}
                  onChange={(event) => {
                    put(index, { title: { ...task.title, [lang]: event.target.value } });
                  }}
                  data-testid={`cat-task-${String(index)}-title-${lang}`}
                />
              ))}
            </Flex>
            <Flex gap={16} wrap align="center">
              <Select
                allowClear
                style={{ minWidth: 240 }}
                placeholder={t('catalog_admin.plan.group_default')}
                aria-label={t('catalog_admin.plan.group')}
                disabled={disabled}
                value={task.group_id ?? undefined}
                onChange={(group: string | undefined) => {
                  put(index, { group_id: group ?? null });
                }}
                options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
              />
              <Checkbox
                checked={task.required}
                disabled={disabled}
                onChange={(event) => {
                  put(index, { required: event.target.checked });
                }}
              >
                {t('catalog_admin.plan.required')}
              </Checkbox>
              <Checkbox
                checked={task.internal}
                disabled={disabled}
                onChange={(event) => {
                  put(index, { internal: event.target.checked });
                }}
              >
                {t('catalog_admin.plan.internal')}
              </Checkbox>
            </Flex>
          </Flex>
        </Card>
      ))}
      <Button
        icon={<PlusOutlined />}
        disabled={disabled || value.length >= 20}
        style={{ alignSelf: 'flex-start' }}
        onClick={() => {
          onChange([
            ...value,
            { title: {}, group_id: null, owner_id: null, required: true, internal: false },
          ]);
        }}
        data-testid="cat-task-add"
      >
        {t('catalog_admin.plan.add')}
      </Button>
    </Flex>
  );
}
