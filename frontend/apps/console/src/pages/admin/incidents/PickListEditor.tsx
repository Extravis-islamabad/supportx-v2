import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons';
import { Badge, Button, Card, Flex, Popconfirm, Space, Table, Tag, Typography } from 'antd';
import { useState } from 'react';

import type { Labels, PickList } from '@supportx/api-client';
import { EmptyText, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { labelled } from '../../incidents/labels';
import { shippedKey, useSettingsSave } from './helpers';
import { ValueDialog } from './shared';

export interface PickValue {
  code: string;
  labels: Labels | null;
  colour?: string | null;
  disabled: boolean;
}

const isAdminValue = (code: string) => code.startsWith('v_');

/**
 * One pick list (REQ-ADM-043): values with translations, order, optional colour, retire and
 * bring back. Retired values are kept (records that use them keep their label) and are shown
 * here, marked. "Other" in a reason list cannot be retired (the server says why).
 */
export function PickListEditor({
  list,
  title,
  description,
  values,
  withColour,
}: {
  list: PickList;
  title: string;
  description?: string;
  values: PickValue[];
  withColour?: boolean;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { save, pending, problems, clear } = useSettingsSave();
  const [editing, setEditing] = useState<PickValue | 'new' | null>(null);
  const name = (v: PickValue) => labelled(v.labels, locale, () => t(shippedKey(list, v.code)));
  const move = (index: number, delta: number) => {
    const codes = values.map((v) => v.code);
    const [moved] = codes.splice(index, 1);
    if (moved === undefined) return;
    codes.splice(index + delta, 0, moved);
    save({ kind: 'order', list, codes });
  };
  const close = () => {
    clear();
    setEditing(null);
  };
  return (
    <Card
      title={title}
      extra={
        <WriteButton
          onClick={() => {
            clear();
            setEditing('new');
          }}
          data-testid={`list-${list}-add`}
        >
          {t('settings.add_value')}
        </WriteButton>
      }
      data-testid={`list-${list}`}
    >
      {description !== undefined && (
        <Typography.Paragraph type="secondary">{description}</Typography.Paragraph>
      )}
      <Table
        size="small"
        rowKey="code"
        pagination={false}
        dataSource={values}
        locale={{ emptyText: <EmptyText>{t('settings.no_values')}</EmptyText> }}
        columns={[
          {
            key: 'order',
            title: t('settings.order'),
            width: 96,
            render: (_: unknown, value: PickValue, index: number) => (
              <Space size={2}>
                <Button
                  size="small"
                  type="text"
                  icon={<ArrowUpOutlined />}
                  aria-label={t('settings.move_up', { name: name(value) })}
                  disabled={index === 0 || pending}
                  onClick={() => {
                    move(index, -1);
                  }}
                  data-testid={`list-${list}-up-${value.code}`}
                />
                <Button
                  size="small"
                  type="text"
                  icon={<ArrowDownOutlined />}
                  aria-label={t('settings.move_down', { name: name(value) })}
                  disabled={index === values.length - 1 || pending}
                  onClick={() => {
                    move(index, 1);
                  }}
                  data-testid={`list-${list}-down-${value.code}`}
                />
              </Space>
            ),
          },
          {
            key: 'name',
            title: t('settings.name'),
            render: (_: unknown, value: PickValue) => (
              <Flex gap={8} align="center" wrap>
                {withColour === true && value.colour != null && <Badge color={value.colour} />}
                <bdi dir="auto" data-testid={`list-${list}-name-${value.code}`}>
                  {name(value)}
                </bdi>
                {value.disabled && (
                  <Tag data-testid={`list-${list}-retired-${value.code}`}>
                    {t('settings.retired')}
                  </Tag>
                )}
              </Flex>
            ),
          },
          {
            key: 'actions',
            title: t('settings.actions'),
            width: 220,
            render: (_: unknown, value: PickValue) => (
              <Space>
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    clear();
                    setEditing(value);
                  }}
                  data-testid={`list-${list}-edit-${value.code}`}
                >
                  {t('settings.rename')}
                </Button>
                {value.disabled ? (
                  <Button
                    type="link"
                    size="small"
                    disabled={pending}
                    onClick={() => {
                      save({ kind: 'value', list, code: value.code, body: { disabled: false } });
                    }}
                    data-testid={`list-${list}-restore-${value.code}`}
                  >
                    {t('settings.bring_back')}
                  </Button>
                ) : (
                  <Popconfirm
                    title={t('settings.retire_confirm', { name: name(value) })}
                    description={t('settings.retire_explained')}
                    okText={t('settings.retire')}
                    cancelText={t('actions.cancel')}
                    onConfirm={() => {
                      save({ kind: 'value', list, code: value.code, body: { disabled: true } });
                    }}
                  >
                    <Button
                      type="link"
                      size="small"
                      data-testid={`list-${list}-retire-${value.code}`}
                    >
                      {t('settings.retire')}
                    </Button>
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />
      {/* Problems of a retire or reorder (not made in a dialog) show under the list. */}
      {editing === null && problems.length > 0 && (
        <Typography.Text type="danger" role="alert" data-testid={`list-${list}-problems`}>
          {problems.join(' ')}
        </Typography.Text>
      )}
      {editing !== null && (
        <ValueDialog
          open
          title={
            editing === 'new'
              ? t('settings.add_value_to', { list: title })
              : t('settings.rename_value', { name: name(editing) })
          }
          shipped={
            editing === 'new' || isAdminValue(editing.code)
              ? null
              : t(shippedKey(list, editing.code))
          }
          labels={editing === 'new' ? null : editing.labels}
          colour={editing === 'new' ? null : (editing.colour ?? null)}
          withColour={withColour}
          pending={pending}
          problems={problems}
          onCancel={close}
          onSave={(labels, colour) => {
            if (editing === 'new') {
              save({ kind: 'add_value', list, labels: labels ?? {}, colour }, close);
            } else {
              save(
                {
                  kind: 'value',
                  list,
                  code: editing.code,
                  body: withColour === true ? { labels, colour } : { labels },
                },
                close,
              );
            }
          }}
          testId={`list-${list}-dialog`}
        />
      )}
    </Card>
  );
}
