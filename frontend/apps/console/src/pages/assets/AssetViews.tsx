import { DeleteOutlined, StarFilled, StarOutlined } from '@ant-design/icons';
import { App, Button, Drawer, Flex, Form, Input, List, Select, Typography } from 'antd';
import { useState } from 'react';

import { useFavouriteView, useSharedSavedViewChange } from '@supportx/api-client';
import { lengthLimit, reportError, useLabel } from '@supportx/ui';

import { TRASH, type ViewChoice } from './views';

/** The view picker on the asset list's toolbar: favourites first, then the rest. */
export function AssetViewPicker({
  value,
  onChange,
  choices,
  withTrash,
}: {
  value: string;
  onChange: (key: string) => void;
  choices: ViewChoice[];
  withTrash: boolean;
}) {
  const t = useLabel();
  const option = (c: ViewChoice) => ({
    value: c.key,
    label: (
      <Flex gap={6} align="center">
        {c.favourite && <StarFilled aria-hidden style={{ color: 'var(--ant-color-warning)' }} />}
        <bdi dir="auto">{c.name}</bdi>
      </Flex>
    ),
    title: c.name,
  });
  const favourites = choices.filter((c) => c.favourite);
  const others = choices.filter((c) => !c.favourite);
  return (
    <Select
      value={value}
      onChange={onChange}
      aria-label={t('assets.views.picker')}
      style={{ minWidth: 220 }}
      popupMatchSelectWidth={false}
      data-testid="assets-view"
      options={[
        ...(favourites.length > 0
          ? [{ label: t('assets.views.favourites'), title: '', options: favourites.map(option) }]
          : []),
        { label: t('assets.views.views'), title: '', options: others.map(option) },
        ...(withTrash
          ? [{ value: TRASH, label: t('assets.record.trash'), title: t('assets.record.trash') }]
          : []),
      ]}
    />
  );
}

/**
 * The views drawer (REQ-AST-047, after REQ-INC-106/107): star a view to put it first, save the
 * list as it is filtered now as a view of your own, or remove one of yours. Kept per person in
 * the shared list-settings store; your other windows follow live.
 */
export function AssetViewsDrawer({
  open,
  onClose,
  choices,
  current,
  filter,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  choices: ViewChoice[];
  current: string;
  /** The list's filter as it is now (the tree node and the search), or null for everything. */
  filter: Record<string, unknown> | null;
  onSaved: (key: string) => void;
}) {
  const t = useLabel();
  const { modal } = App.useApp();
  const star = useFavouriteView('assets');
  const change = useSharedSavedViewChange('assets');
  const [name, setName] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID());
  const save = () => {
    change.mutate(
      { kind: 'create', key, view: { name: name.trim(), filter, columns: [], favourite: false } },
      {
        onSuccess: (made) => {
          setName('');
          setKey(crypto.randomUUID());
          if (made !== null) onSaved(made.view_key);
        },
        onError: reportError,
      },
    );
  };
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('assets.views.title')}
      // Never wider than a phone's screen (the visual matrix's 390 px).
      width="min(420px, 100vw)"
      data-testid="assets-views-drawer"
    >
      <Flex vertical gap={16}>
        <Typography.Text type="secondary">{t('assets.views.intro')}</Typography.Text>
        <List
          size="small"
          dataSource={choices}
          data-testid="assets-views-list"
          renderItem={(choice) => {
            const label = t(choice.favourite ? 'assets.views.unstar' : 'assets.views.star', {
              name: choice.name,
            });
            return (
              <List.Item
                actions={[
                  <Button
                    key="star"
                    type="text"
                    aria-pressed={choice.favourite}
                    aria-label={label}
                    title={label}
                    icon={choice.favourite ? <StarFilled /> : <StarOutlined />}
                    loading={star.isPending && star.variables.viewKey === choice.key}
                    onClick={() => {
                      star.mutate(
                        { viewKey: choice.key, favourite: !choice.favourite },
                        { onError: reportError },
                      );
                    }}
                    data-testid={`assets-view-star-${choice.key}`}
                  />,
                  ...(choice.saved === undefined
                    ? []
                    : [
                        <Button
                          key="delete"
                          type="text"
                          danger
                          aria-label={t('assets.views.delete', { name: choice.name })}
                          title={t('assets.views.delete', { name: choice.name })}
                          icon={<DeleteOutlined />}
                          onClick={() => {
                            const saved = choice.saved;
                            if (saved?.saved_view_id == null || saved.version == null) return;
                            const id = saved.saved_view_id;
                            const version = saved.version;
                            modal.confirm({
                              title: t('assets.views.delete_confirm', { name: choice.name }),
                              okText: t('assets.views.delete_ok'),
                              okButtonProps: { danger: true },
                              cancelText: t('actions.cancel'),
                              onOk: () =>
                                change.mutateAsync({ kind: 'delete', id, version }).then(() => {
                                  if (current === choice.key) onSaved('all');
                                }, reportError),
                            });
                          }}
                          data-testid={`assets-view-delete-${choice.saved.saved_view_id ?? ''}`}
                        />,
                      ]),
                ]}
              >
                <bdi dir="auto" style={{ fontWeight: choice.key === current ? 600 : undefined }}>
                  {choice.name}
                </bdi>
              </List.Item>
            );
          }}
        />
        <Form layout="vertical" onFinish={save}>
          <Form.Item
            label={t('assets.views.save_label')}
            htmlFor="assets-view-name"
            extra={t('assets.views.save_hint')}
          >
            <Flex gap={8}>
              <Input
                id="assets-view-name"
                value={name}
                count={lengthLimit(120)}
                onChange={(event) => {
                  setName(event.target.value);
                }}
                data-testid="assets-view-name"
              />
              <Button
                type="primary"
                htmlType="submit"
                disabled={name.trim() === ''}
                loading={change.isPending}
                data-testid="assets-view-save"
              >
                {t('actions.save')}
              </Button>
            </Flex>
          </Form.Item>
        </Form>
      </Flex>
    </Drawer>
  );
}
