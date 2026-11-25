import { Form, Modal, Select } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import {
  useCatalogItems,
  useChangeTemplates,
  useIncidentTemplates,
  type AssetRecord,
} from '@supportx/api-client';
import { useAppearance, useLabel } from '@supportx/ui';

import { templateName } from '../changes/labels';
import { templateLabel } from '../incidents/labels';
import { itemName } from '../requests/items';
import { raisePath, type RaiseKind } from './raise';

/**
 * Raise an incident, service request or change from an asset (WP-049b s4a; REQ-AST-045): pick a
 * template (only those you may use: each list is the one its own create form offers), then the
 * normal create form opens with the asset and the person who holds it filled in. A change takes
 * no asset on its form yet, so only its requester is filled in.
 *
 * The asset's history line "INC-n raised from this asset" comes from work items' link event
 * (`at_creation`), once lane A's side is on main.
 */
export function RaiseFromAssetDialog({
  asset,
  kind,
  onClose,
}: {
  asset: AssetRecord;
  kind: RaiseKind;
  onClose: () => void;
}) {
  const t = useLabel();
  return (
    <RaiseDialog
      kind={kind}
      testPrefix="asset"
      title={t(`assets.raise.title_${kind}`)}
      hint={t('assets.raise.hint')}
      pathOf={(template) => raisePath(kind, template, asset)}
      onClose={onClose}
    />
  );
}

/**
 * Pick the template (or, for a request, the catalogue item) and open the create form at
 * `pathOf(id)`. Shared by the asset page and the CI page (WP-053 S5c): each list is the one its
 * own create form offers, so nothing appears here that the form would not accept.
 */
export function RaiseDialog({
  kind,
  testPrefix,
  title,
  hint,
  pathOf,
  onClose,
}: {
  kind: RaiseKind;
  testPrefix: string;
  title: string;
  hint: string;
  pathOf: (id: string) => string;
  onClose: () => void;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const [chosen, setChosen] = useState<string>();
  const id = `${testPrefix}-raise-template`;
  return (
    <Modal
      open
      title={title}
      okText={t('assets.raise.open_form')}
      okButtonProps={{ disabled: chosen === undefined, 'data-testid': `${testPrefix}-raise-ok` }}
      cancelText={t('actions.cancel')}
      onCancel={onClose}
      onOk={() => {
        if (chosen === undefined) return;
        void navigate(pathOf(chosen));
        onClose();
      }}
      data-testid={`${testPrefix}-raise-dialog`}
    >
      <Form layout="vertical">
        <Form.Item
          label={t(kind === 'service_request' ? 'assets.raise.item' : 'assets.raise.template')}
          htmlFor={id}
          extra={hint}
        >
          {kind === 'incident' && <IncidentChoice id={id} value={chosen} onChange={setChosen} />}
          {kind === 'service_request' && <ItemChoice id={id} value={chosen} onChange={setChosen} />}
          {kind === 'change' && <ChangeChoice id={id} value={chosen} onChange={setChosen} />}
        </Form.Item>
      </Form>
    </Modal>
  );
}

interface ChoiceProps {
  id: string;
  value: string | undefined;
  onChange: (id: string) => void;
}

function Choice({
  id,
  options,
  loading,
  value,
  onChange,
}: ChoiceProps & { options: { value: string; label: string }[]; loading: boolean }) {
  const t = useLabel();
  return (
    <Select
      id={id}
      showSearch
      optionFilterProp="label"
      value={value}
      onChange={onChange}
      options={options}
      loading={loading}
      notFoundContent={t('assets.raise.none')}
      data-testid={id}
    />
  );
}

// One list per kind, each the one its create form offers (the server lists only templates the
// person may use; disabled ones are never offered), read only when that kind is chosen.
function IncidentChoice(props: ChoiceProps) {
  const t = useLabel();
  const { locale } = useAppearance();
  const found = useIncidentTemplates();
  const options = (found.data ?? [])
    .filter((x) => !x.disabled)
    .map((x) => ({ value: x.id, label: templateLabel(t, x, locale) }));
  return <Choice {...props} options={options} loading={found.isPending} />;
}

function ItemChoice(props: ChoiceProps) {
  const { locale } = useAppearance();
  const found = useCatalogItems();
  const options = (found.data ?? [])
    .filter((i) => i.status === 'published' && i.kind === 'service')
    .map((i) => ({ value: i.id, label: itemName(i, locale) }));
  return <Choice {...props} options={options} loading={found.isPending} />;
}

function ChangeChoice(props: ChoiceProps) {
  const t = useLabel();
  const { locale } = useAppearance();
  const found = useChangeTemplates();
  const options = (found.data ?? [])
    .filter((x) => !x.disabled)
    .map((x) => ({ value: x.id, label: templateName(t, locale, x) }));
  return <Choice {...props} options={options} loading={found.isPending} />;
}
