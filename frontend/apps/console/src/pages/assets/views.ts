import {
  useSharedListSettings,
  type AssetView,
  type SharedViewSetting,
} from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/** The asset list's built-in views (WP-049b s4a; REQ-AST-047), in the order the picker shows. */
export const BUILT_IN: readonly AssetView[] = [
  'all',
  'mine',
  'in_stock',
  'loanable',
  'warranty_expiring',
  'scan_failures',
  'recently_discovered',
];
export const TRASH = 'trash';
const CUSTOM = 'custom:';

export const isBuiltIn = (key: string): key is AssetView =>
  (BUILT_IN as readonly string[]).includes(key);

/** What the picker offers: built-in views, your saved views, favourites first (REQ-INC-107). */
export interface ViewChoice {
  key: string;
  name: string;
  favourite: boolean;
  saved?: SharedViewSetting;
}

export function useAssetViewChoices(enabled: boolean): {
  choices: ViewChoice[];
  saved: (key: string) => SharedViewSetting | undefined;
} {
  const t = useLabel();
  const mine = useSharedListSettings('assets', enabled);
  const rows = new Map((mine.data?.views ?? []).map((v) => [v.view_key, v]));
  const builtIn: ViewChoice[] = BUILT_IN.map((key) => ({
    key,
    name: t(`asset_view.${key}`),
    favourite: rows.get(key)?.favourite ?? false,
  }));
  const own: ViewChoice[] = (mine.data?.views ?? [])
    .filter((v) => v.view_key.startsWith(CUSTOM))
    .map((v) => ({ key: v.view_key, name: v.name ?? '', favourite: v.favourite, saved: v }));
  const all = [...builtIn, ...own];
  return {
    choices: [...all.filter((c) => c.favourite), ...all.filter((c) => !c.favourite)],
    saved: (key) => (key.startsWith(CUSTOM) ? rows.get(key) : undefined),
  };
}
