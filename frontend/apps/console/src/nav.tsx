import {
  AppstoreOutlined,
  BarChartOutlined,
  BookOutlined,
  BugOutlined,
  ClusterOutlined,
  HomeOutlined,
  InboxOutlined,
  RocketOutlined,
  SettingOutlined,
  SwapOutlined,
} from '@ant-design/icons';

import type { NavItem } from '@supportx/ui';

/**
 * Console sections. `feature` ties a section to the licence (WP-009): sections outside the plan
 * are hidden, or shown locked to tenant admins (see visibleNav in @supportx/ui).
 */
export const NAV: readonly NavItem[] = [
  { key: 'home', path: '/', labelKey: 'nav.home', icon: <HomeOutlined /> },
  {
    key: 'requests',
    path: '/requests',
    labelKey: 'nav.requests',
    icon: <InboxOutlined />,
    feature: 'incident',
  },
  {
    key: 'problems',
    path: '/problems',
    labelKey: 'nav.problems',
    icon: <BugOutlined />,
    feature: 'problem',
  },
  {
    key: 'changes',
    path: '/changes',
    labelKey: 'nav.changes',
    icon: <SwapOutlined />,
    feature: 'change',
  },
  {
    key: 'releases',
    path: '/releases',
    labelKey: 'nav.releases',
    icon: <RocketOutlined />,
    feature: 'release',
  },
  {
    key: 'assets',
    path: '/assets',
    labelKey: 'nav.assets',
    icon: <AppstoreOutlined />,
    feature: 'assets',
  },
  { key: 'cmdb', path: '/cmdb', labelKey: 'nav.cmdb', icon: <ClusterOutlined />, feature: 'cmdb' },
  {
    key: 'knowledge',
    path: '/knowledge',
    labelKey: 'nav.knowledge',
    icon: <BookOutlined />,
    feature: 'knowledge',
  },
  { key: 'reports', path: '/reports', labelKey: 'nav.reports', icon: <BarChartOutlined /> },
  {
    key: 'admin',
    path: '/admin/users',
    labelKey: 'nav.admin',
    icon: <SettingOutlined />,
    adminOnly: true,
  },
];

/** Sections that only show "coming soon" until their module exists. */
export const SECTION_KEYS = [
  'requests',
  'problems',
  'changes',
  'releases',
  'assets',
  'cmdb',
  'knowledge',
  'reports',
] as const;

export function navItem(key: string): NavItem | undefined {
  return NAV.find((item) => item.key === key);
}
