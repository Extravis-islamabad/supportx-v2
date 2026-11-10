import { Form, Modal, Select, Switch } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useCreateCatalogCategory,
  useDeleteCatalogCategory,
  useUpdateCatalogCategory,
  type CatalogCategory,
  type Labels,
} from '@supportx/api-client';
import { markHandled, reportError, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { fieldMessages, refusalMessages } from '../incidents/helpers';
import { LabelsFields, Problems } from '../incidents/shared';
import { ICONS } from './icons';
import { categoryPaths, possibleParents } from './tree';

/** Add or change a category (WP-031 plan D1): names, place in the tree, icon, on or off. */
export function CategoryDialog({
  category,
  parentId,
  categories,
  onClose,
}: {
  category?: CatalogCategory;
  parentId?: string;
  categories: CatalogCategory[];
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const [names, setNames] = useState<Labels>(category?.names ?? {});
  const [parent, setParent] = useState<string | null>(category?.parent_id ?? parentId ?? null);
  const [icon, setIcon] = useState<string | null>(category?.icon ?? null);
  const [enabled, setEnabled] = useState(category?.enabled ?? true);
  const [problems, setProblems] = useState<string[]>([]);
  const create = useCreateCatalogCategory();
  const update = useUpdateCatalogCategory();
  const remove = useDeleteCatalogCategory();
  const [key] = useState(() => crypto.randomUUID());
  const paths = categoryPaths(categories, locale);

  const refused = (error: unknown) => {
    const shown = refusalMessages(t, error, fieldMessages(t, error));
    if (shown.length > 0) setProblems(shown);
    else reportError(error);
  };

  const save = () => {
    setProblems([]);
    const body = { names, parent_id: parent, icon, enabled };
    if (category === undefined) {
      create.mutate(
        { body: { ...body, sort_order: categories.length * 10 }, key },
        { onSuccess: onClose, onError: refused },
      );
    } else {
      update.mutate(
        { id: category.id, body, version: category.version },
        { onSuccess: onClose, onError: refused },
      );
    }
  };

  return (
    <Modal
      open
      title={t(
        category === undefined ? 'catalog_admin.new_category' : 'catalog_admin.edit_category',
      )}
      onCancel={onClose}
      onOk={save}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      confirmLoading={create.isPending || update.isPending}
      okButtonProps={{ 'data-testid': 'cat-category-save' }}
      footer={(buttons) => (
        <>
          {category !== undefined && (
            <WriteButton
              danger
              style={{ float: 'inline-start' }}
              loading={remove.isPending}
              data-testid="cat-category-delete"
              onClick={() => {
                remove.mutate(
                  { id: category.id, version: category.version },
                  {
                    onSuccess: onClose,
                    onError: (error) => {
                      if (error instanceof ApiError && error.code === 'service_category_in_use') {
                        markHandled(error);
                        setProblems([t('errors.service_category_in_use')]);
                        return;
                      }
                      reportError(error);
                    },
                  },
                );
              }}
            >
              {t('actions.delete')}
            </WriteButton>
          )}
          {buttons}
        </>
      )}
      destroyOnHidden
      data-testid="cat-category-dialog"
    >
      <Problems problems={problems} testId="cat-category-problems" />
      <Form layout="vertical" onFinish={save}>
        <LabelsFields value={names} onChange={setNames} testId="cat-category-name" />
        <Form.Item label={t('catalog_admin.parent')} htmlFor="cat-category-parent">
          <Select
            id="cat-category-parent"
            allowClear
            placeholder={t('catalog_admin.top_level')}
            value={parent ?? undefined}
            onChange={(value: string | undefined) => {
              setParent(value ?? null);
            }}
            options={possibleParents(categories, category?.id).map((c) => ({
              value: c.id,
              label: paths.get(c.id),
            }))}
            data-testid="cat-category-parent"
          />
        </Form.Item>
        <Form.Item label={t('catalog_admin.icon')} htmlFor="cat-category-icon">
          <Select
            id="cat-category-icon"
            allowClear
            value={icon ?? undefined}
            onChange={(value: string | undefined) => {
              setIcon(value ?? null);
            }}
            options={ICONS.map((code) => ({ value: code, label: t(`catalog_icon.${code}`) }))}
          />
        </Form.Item>
        <Form.Item
          label={t('catalog_admin.category_enabled')}
          help={t('catalog_admin.category_enabled_help')}
        >
          <Switch
            checked={enabled}
            onChange={setEnabled}
            aria-label={t('catalog_admin.category_enabled')}
            data-testid="cat-category-enabled"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
