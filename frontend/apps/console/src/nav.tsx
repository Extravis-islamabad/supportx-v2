import {
  AppstoreOutlined,
  BarChartOutlined,
  BookOutlined,
  BugOutlined,
  ClusterOutlined,
  HomeOutlined,
  InboxOutlined,
  NotificationOutlined,
  RocketOutlined,
  SettingOutlined,
  SwapOutlined,
} from '@ant-design/icons';

import { ADMIN_PERMISSIONS, type NavItem } from '@supportx/ui';

/**
 * Console sections. `permissions` decide who sees a section (WP-016); `feature` ties it to the
 * licence (WP-009): outside the plan it is hidden, or shown locked to whoever manages the licence.
 */
export const NAV: readonly NavItem[] = [
  { key: 'home', path: '/', labelKey: 'nav.home', icon: <HomeOutlined /> },
  {
    key: 'requests',
    path: '/requests',
    labelKey: 'nav.requests',
    icon: <InboxOutlined />,
    feature: 'incident',
    permissions: ['requests.view'],
  },
  {
    key: 'problems',
    path: '/problems',
    labelKey: 'nav.problems',
    icon: <BugOutlined />,
    feature: 'problem',
    permissions: ['problems.view'],
  },
  {
    key: 'changes',
    path: '/changes',
    labelKey: 'nav.changes',
    icon: <SwapOutlined />,
    feature: 'change',
    permissions: ['changes.view'],
  },
  {
    key: 'releases',
    path: '/releases',
    labelKey: 'nav.releases',
    icon: <RocketOutlined />,
    feature: 'release',
    permissions: ['releases.view'],
  },
  {
    key: 'assets',
    path: '/assets',
    labelKey: 'nav.assets',
    icon: <AppstoreOutlined />,
    feature: 'assets',
    permissions: ['assets.view'],
  },
  {
    key: 'cmdb',
    path: '/cmdb',
    labelKey: 'nav.cmdb',
    icon: <ClusterOutlined />,
    feature: 'cmdb',
    permissions: ['cmdb.view'],
  },
  {
    key: 'knowledge',
    path: '/knowledge',
    labelKey: 'nav.knowledge',
    icon: <BookOutlined />,
    feature: 'knowledge',
    permissions: ['knowledge.view'],
  },
  {
    key: 'announcements',
    path: '/announcements',
    labelKey: 'nav.announcements',
    icon: <NotificationOutlined />,
    feature: 'incident',
    permissions: ['announcements.view'],
  },
  {
    key: 'reports',
    path: '/reports',
    labelKey: 'nav.reports',
    icon: <BarChartOutlined />,
    permissions: ['reports.view'],
  },
  {
    key: 'admin',
    path: '/admin',
    labelKey: 'nav.admin',
    icon: <SettingOutlined />,
    permissions: ADMIN_PERMISSIONS,
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
