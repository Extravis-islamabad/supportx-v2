import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { App, Button, Card, Flex, Input, Select, Typography } from 'antd';
import { useMemo, useState } from 'react';

import {
  ApiError,
  useSaveSiteNetworks,
  useSiteNetworks,
  useStructure,
  type SiteNetworkEntry,
} from '@supportx/api-client';
import {
  FormProblem,
  markHandled,
  useDateTime,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

const MAX_ENTRIES = 200; // the server's cap (domain/place.py MAX_SITE_NETWORKS)

interface Row {
  key: number;
  network: string;
  site_id: string | null;
}

let nextKey = 0;
function rowsFrom(entries: SiteNetworkEntry[]): Row[] {
  return entries.map((entry) => ({
    key: nextKey++,
    network: entry.network,
    site_id: entry.site_id,
  }));
}

/**
 * Address ranges by site (WP-057 S2b-1, D-170 item 2): a sign-in from a mapped range shows the
 * site ("Islamabad HQ") instead of "Internal network" or a city. The most specific range wins.
 * Saved as one list and audited. The card also says how old the installed place database is.
 */
export function SiteNetworksCard() {
  const t = useLabel();
  const dates = useDateTime();
  const { message } = App.useApp();
  const saved = useSiteNetworks();
  const sites = useStructure('sites');
  const save = useSaveSiteNetworks();
  const [edited, setEdited] = useState<Row[] | null>(null);
  const [refused, setRefused] = useState<Record<number, string>>({});
  const problem = useFormProblem();
  // Keys made once per saved list: new keys on every render would recreate the inputs (and lose
  // the typing and the focus) whenever anything else re-renders the card.
  const savedRows = useMemo(() => rowsFrom(saved.data?.entries ?? []), [saved.data]);
  if (saved.data === undefined) return <Card loading data-testid="security-site-networks" />;
  const rows = edited ?? savedRows;
  const options = (sites.data ?? [])
    .filter((site) => !site.disabled)
    .map((site) => ({ value: site.id, label: site.name }));
  const change = (index: number, patch: Partial<Row>) => {
    setEdited(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    setRefused((current) => ({ ...current, [index]: '' }));
  };
  const complete = rows.every((row) => row.network.trim() !== '' && row.site_id !== null);
  const submit = () => {
    problem.clear();
    const entries = rows.map((row) => ({
      network: row.network.trim(),
      site_id: row.site_id ?? '',
    }));
    save.mutate(
      { entries, version: saved.data.version },
      {
        onSuccess: (next) => {
          setEdited(rowsFrom(next.entries));
          setRefused({});
          void message.success(t('security.site_networks.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
            markHandled(error);
            const found: Record<number, string> = {};
            for (const field of error.fieldErrors) {
              const index = Number(/^entries\.(\d+)$/.exec(field.field)?.[1]);
              if (Number.isInteger(index)) found[index] = t(field.message_key, field.params ?? {});
              else problem.show(error);
            }
            setRefused(found);
            return;
          }
          if (error instanceof ApiError && error.isConflict) markHandled(error);
          problem.show(error);
        },
      },
    );
  };
  const built = saved.data.geoip_built_at;
  return (
    <Card title={t('security.site_networks.title')} data-testid="security-site-networks">
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.site_networks.intro')}
        </Typography.Paragraph>
        {rows.length === 0 && (
          <Typography.Text type="secondary" data-testid="security-site-networks-none">
            {t('security.site_networks.none')}
          </Typography.Text>
        )}
        {rows.map((row, index) => (
          <Flex
            key={row.key}
            vertical
            gap={4}
            data-testid={`security-site-network-${String(index)}`}
          >
            <Flex gap={8} wrap align="center">
              <Input
                aria-label={t('security.site_networks.range')}
                dir="ltr"
                style={{ width: 200, maxWidth: '100%' }}
                value={row.network}
                placeholder="10.1.0.0/16"
                status={refused[index] ? 'error' : undefined}
                onChange={(event) => {
                  change(index, { network: event.target.value });
                }}
                data-testid={`security-site-network-${String(index)}-range`}
              />
              <Select
                aria-label={t('security.site_networks.site')}
                style={{ width: 220, maxWidth: '100%' }}
                value={row.site_id}
                options={options}
                placeholder={t('security.site_networks.choose_site')}
                showSearch
                optionFilterProp="label"
                onChange={(value: string) => {
                  change(index, { site_id: value });
                }}
                data-testid={`security-site-network-${String(index)}-site`}
              />
              <Button
                type="text"
                icon={<DeleteOutlined />}
                aria-label={t('security.site_networks.remove')}
                onClick={() => {
                  setEdited(rows.filter((_row, i) => i !== index));
                  setRefused({});
                }}
                data-testid={`security-site-network-${String(index)}-remove`}
              />
            </Flex>
            {refused[index] ? (
              <Typography.Text type="danger" role="alert">
                {refused[index]}
              </Typography.Text>
            ) : null}
          </Flex>
        ))}
        <div>
          <Button
            icon={<PlusOutlined />}
            disabled={rows.length >= MAX_ENTRIES}
            onClick={() => {
              setEdited([...rows, { key: nextKey++, network: '', site_id: null }]);
            }}
            data-testid="security-site-networks-add"
          >
            {t('security.site_networks.add')}
          </Button>
        </div>
        <Typography.Text type="secondary" data-testid="security-geoip-date">
          {built == null
            ? t('security.site_networks.no_database')
            : t('security.site_networks.database_date', { date: dates.format(built) })}
        </Typography.Text>
        <div>
          <FormProblem problem={problem} />
          <WriteButton
            loading={save.isPending}
            disabled={edited === null || !complete}
            onClick={submit}
            data-testid="security-site-networks-save"
          >
            {t('actions.save')}
          </WriteButton>
        </div>
      </Flex>
    </Card>
  );
}
