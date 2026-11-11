import { useQueryClient } from '@tanstack/react-query';
import { Alert, Flex, Skeleton, Tabs } from 'antd';
import { useSearchParams } from 'react-router';

import {
  queryKeys,
  useAssetLifeCycles,
  useAssetProductTypes,
  useAssetSettings,
  useAssetStates,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import { PageHeader, useLabel, useLicence } from '@supportx/ui';

import { LifeCyclesTab } from './LifeCyclesTab';
import { ProductsTab } from './ProductsTab';
import { OverdueRuleCard } from './OverdueRuleCard';
import { SettingsTab } from './SettingsTab';
import { StatesTab } from './StatesTab';
import { StockRulesTab } from './StockRulesTab';
import { TypesTab } from './TypesTab';

const TAB_KEYS = ['types', 'products', 'states', 'life_cycles', 'stock_rules', 'settings'];

/**
 * The asset catalogue (WP-049a, D-141): product types, products, states, life cycles and the
 * asset settings, for config.assets (or settings.manage). Another admin's change arrives live:
 * `assets.catalogue_changed` carries no IDs (§5c), so every asset query refetches. Outside the
 * plan (feature `assets`) the page says so instead of failing on the server's refusal.
 */
export function AssetCatalogPage() {
  const t = useLabel();
  const licence = useLicence();
  const queryClient = useQueryClient();
  // ?tab=products opens that tab (the asset form's "no products yet" hint links there).
  const [params] = useSearchParams();
  const licensed = licence.has('assets');
  const settings = useAssetSettings(licensed);
  const states = useAssetStates(licensed);
  const lifeCycles = useAssetLifeCycles(licensed);
  const types = useAssetProductTypes(licensed);
  useTenantChannel((event) => {
    if (event.type === 'assets.catalogue_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
    }
  });
  const header = <PageHeader title={t('nav.admin_assets')} />;
  if (!licensed) {
    return (
      <Flex vertical gap={16}>
        {header}
        <Alert
          type="info"
          showIcon
          message={t('licence.locked')}
          description={t(licence.isAdmin ? 'licence.upgrade_hint' : 'licence.ask_admin')}
          data-testid="asset-catalogue-locked"
        />
      </Flex>
    );
  }
  if (
    settings.data === undefined ||
    states.data === undefined ||
    lifeCycles.data === undefined ||
    types.data === undefined
  ) {
    return <Skeleton active />;
  }
  return (
    <Flex vertical gap={16}>
      {header}
      <Tabs
        destroyOnHidden
        defaultActiveKey={TAB_KEYS.find((key) => key === params.get('tab'))}
        items={[
          {
            key: 'types',
            label: t('assets.admin.product_types'),
            children: <TypesTab types={types.data} lifeCycles={lifeCycles.data} />,
          },
          {
            key: 'products',
            label: t('assets.admin.products'),
            children: <ProductsTab types={types.data} />,
          },
          {
            key: 'states',
            label: t('assets.admin.states'),
            children: <StatesTab states={states.data} />,
          },
          {
            key: 'life_cycles',
            label: t('assets.admin.life_cycles'),
            children: <LifeCyclesTab lifeCycles={lifeCycles.data} states={states.data} />,
          },
          {
            // WP-049b s1 (REQ-AST-035): minimum stock and who hears of it.
            key: 'stock_rules',
            label: t('assets.rules.title'),
            children: <StockRulesTab types={types.data} />,
          },
          {
            key: 'settings',
            label: t('assets.admin.settings'),
            children: (
              <Flex vertical gap={16}>
                <SettingsTab settings={settings.data} />
                {/* WP-049b s3 (REQ-AST-056): the overdue-scan rule, off by default. */}
                <OverdueRuleCard />
              </Flex>
            ),
          },
        ]}
        data-testid="asset-catalogue-tabs"
      />
    </Flex>
  );
}
