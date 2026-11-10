import { useQueryClient } from '@tanstack/react-query';
import { Button, Checkbox, Flex, Form, Input, Modal, Popconfirm, Table } from 'antd';
import { useState } from 'react';

import { queryKeys, useVendorChange, useVendors, type Vendor } from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  CellText,
  EmptyText,
  ListPage,
  NoAccess,
  PageHeader,
  lengthLimit,
  reportError,
  ToneTag,
  useAccess,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { Problems } from '../admin/incidents/shared';
import { useAssetSaveProblems } from './problems';

const FIELDS = [
  ['name', 200],
  ['contact_person', 120],
  ['email', 254],
  ['phone', 120],
  ['fax', 120],
  ['website', 300],
  ['currency', 3],
  ['address', 2000],
  ['description', 2000],
] as const;
type Field = (typeof FIELDS)[number][0];
type Draft = Record<Field, string> & { is_active: boolean };

const draftOf = (vendor: Vendor | null): Draft => ({
  name: vendor?.name ?? '',
  contact_person: vendor?.contact_person ?? '',
  email: vendor?.email ?? '',
  phone: vendor?.phone ?? '',
  fax: vendor?.fax ?? '',
  website: vendor?.website ?? '',
  currency: vendor?.currency ?? '',
  address: vendor?.address ?? '',
  description: vendor?.description ?? '',
  is_active: vendor?.is_active ?? true,
});

/**
 * Vendors as their own list (REQ-PUR-001; WP-049a s2): add, change, make inactive, delete.
 * An inactive vendor stays on the records that name it; one still named cannot be deleted.
 * Another person's change arrives live (procurement.vendors_changed).
 */
export function VendorsPage() {
  const t = useLabel();
  const access = useAccess();
  const queryClient = useQueryClient();
  const allowed = access.can('vendors.view');
  const vendors = useVendors(false, allowed);
  const change = useVendorChange();
  const { problems, show, clear } = useAssetSaveProblems();
  const [editing, setEditing] = useState<{ vendor: Vendor | null; draft: Draft; key: string }>();
  useTenantChannel((message) => {
    if (message.type === 'procurement.vendors_changed' || message.type === 'refresh') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.vendors.all });
    }
  });
  if (!allowed) return <NoAccess titleKey="assets.record.vendors" />;
  const rows = vendors.data?.pages.flatMap((p) => p.items) ?? [];
  const canAdd = access.can('vendors.create');
  const canManage = access.can('vendors.manage');
  const open = (vendor: Vendor | null) => {
    clear();
    setEditing({ vendor, draft: draftOf(vendor), key: crypto.randomUUID() });
  };
  const save = () => {
    if (editing === undefined) return;
    const blank = (v: string) => (v.trim() === '' ? null : v.trim());
    const all: Record<string, unknown> = Object.fromEntries(
      FIELDS.map(([field]) => [
        field,
        field === 'name' ? editing.draft.name.trim() : blank(editing.draft[field]),
      ]),
    );
    const close = () => {
      setEditing(undefined);
    };
    if (editing.vendor === null) {
      const body = Object.fromEntries(Object.entries(all).filter(([, v]) => v !== null));
      change.mutate(
        { kind: 'create', key: editing.key, body: body as never },
        { onSuccess: close, onError: show },
      );
      return;
    }
    const before = draftOf(editing.vendor);
    const body: Record<string, unknown> = Object.fromEntries(
      FIELDS.filter(([field]) => editing.draft[field] !== before[field]).map(([field]) => [
        field,
        all[field],
      ]),
    );
    if (editing.draft.is_active !== before.is_active) body.is_active = editing.draft.is_active;
    change.mutate(
      { kind: 'update', id: editing.vendor.id, version: editing.vendor.version, body },
      { onSuccess: close, onError: show },
    );
  };
  // The server's count when it gives one, else the rows when they are all loaded.
  const total =
    vendors.data === undefined
      ? undefined
      : (vendors.data.pages[0]?.estimated_total ?? (vendors.hasNextPage ? undefined : rows.length));
  return (
    <ListPage
      testId="vendors-page"
      header={
        <PageHeader
          title={t('assets.record.vendors')}
          count={total === undefined ? undefined : String(total)}
          extra={
            canAdd && (
              <WriteButton
                type="primary"
                onClick={() => {
                  open(null);
                }}
                data-testid="vendor-add"
              >
                {t('actions.add')}
              </WriteButton>
            )
          }
        />
      }
    >
      <Table<Vendor>
        size="small"
        rowKey="id"
        pagination={false}
        loading={vendors.isLoading}
        dataSource={rows}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyText>{t('assets.record.no_vendors')}</EmptyText> }}
        columns={[
          {
            key: 'name',
            title: t('settings.name'),
            render: (_: unknown, vendor: Vendor) => (
              <Flex gap={8} align="center">
                <span data-testid={`vendor-name-${vendor.id}`}>
                  <CellText title={vendor.name}>{vendor.name}</CellText>
                </span>
                {!vendor.is_active && (
                  <ToneTag tone="default">{t('assets.record.inactive')}</ToneTag>
                )}
              </Flex>
            ),
          },
          {
            key: 'contact',
            title: t('assets.record.contact_person'),
            render: (_: unknown, vendor: Vendor) => (
              <CellText>{vendor.contact_person ?? ''}</CellText>
            ),
          },
          {
            key: 'email',
            title: t('assets.record.email'),
            render: (_: unknown, vendor: Vendor) => <bdi dir="ltr">{vendor.email ?? ''}</bdi>,
          },
          {
            key: 'phone',
            title: t('assets.record.phone'),
            render: (_: unknown, vendor: Vendor) => <bdi dir="ltr">{vendor.phone ?? ''}</bdi>,
          },
          {
            key: 'actions',
            title: <span className="sr-only">{t('assets.admin.actions')}</span>,
            render: (_: unknown, vendor: Vendor) =>
              canManage && (
                <Flex gap={4} justify="end">
                  <Button
                    type="link"
                    onClick={() => {
                      open(vendor);
                    }}
                    data-testid={`vendor-edit-${vendor.id}`}
                  >
                    {t('actions.edit')}
                  </Button>
                  <Popconfirm
                    title={t('assets.admin.delete_confirm', { name: vendor.name })}
                    okText={t('actions.delete')}
                    cancelText={t('actions.cancel')}
                    onConfirm={() => {
                      change.mutate(
                        { kind: 'delete', id: vendor.id, version: vendor.version },
                        { onError: reportError },
                      );
                    }}
                  >
                    <Button type="link" danger>
                      {t('actions.delete')}
                    </Button>
                  </Popconfirm>
                </Flex>
              ),
          },
        ]}
      />
      <Modal
        open={editing !== undefined}
        width={640}
        title={
          editing?.vendor === null ? t('assets.record.add_vendor') : t('assets.record.edit_vendor')
        }
        okText={t('actions.save')}
        cancelText={t('actions.cancel')}
        onOk={save}
        onCancel={() => {
          setEditing(undefined);
        }}
        confirmLoading={change.isPending}
        destroyOnHidden
        data-testid="vendor-dialog"
      >
        {editing !== undefined && (
          <Form layout="vertical">
            <Problems problems={problems} testId="vendor-problems" />
            {FIELDS.map(([field, max]) => (
              <Form.Item
                key={field}
                label={t(`assets.record.${field === 'name' ? 'vendor_name' : field}`)}
                htmlFor={`vendor-${field}`}
                required={field === 'name'}
              >
                {field === 'address' || field === 'description' ? (
                  <Input.TextArea
                    id={`vendor-${field}`}
                    dir="auto"
                    rows={2}
                    count={lengthLimit(max)}
                    value={editing.draft[field]}
                    onChange={(event) => {
                      setEditing({
                        ...editing,
                        draft: { ...editing.draft, [field]: event.target.value },
                      });
                    }}
                  />
                ) : (
                  <Input
                    id={`vendor-${field}`}
                    dir={
                      ['email', 'phone', 'fax', 'website', 'currency'].includes(field)
                        ? 'ltr'
                        : 'auto'
                    }
                    count={lengthLimit(max)}
                    value={editing.draft[field]}
                    onChange={(event) => {
                      const value =
                        field === 'currency'
                          ? event.target.value.toUpperCase()
                          : event.target.value;
                      setEditing({ ...editing, draft: { ...editing.draft, [field]: value } });
                    }}
                    data-testid={`vendor-${field}`}
                  />
                )}
              </Form.Item>
            ))}
            {editing.vendor !== null && (
              <Checkbox
                checked={editing.draft.is_active}
                onChange={(event) => {
                  setEditing({
                    ...editing,
                    draft: { ...editing.draft, is_active: event.target.checked },
                  });
                }}
                data-testid="vendor-active"
              >
                {t('assets.record.active_help')}
              </Checkbox>
            )}
          </Form>
        )}
      </Modal>
    </ListPage>
  );
}
