import {
  ApiOutlined,
  AppstoreOutlined,
  BankOutlined,
  CalendarOutlined,
  CarOutlined,
  DesktopOutlined,
  DollarOutlined,
  FileTextOutlined,
  GlobalOutlined,
  HomeOutlined,
  IdcardOutlined,
  KeyOutlined,
  LaptopOutlined,
  MailOutlined,
  MobileOutlined,
  PrinterOutlined,
  QuestionCircleOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  ToolOutlined,
  UserAddOutlined,
  UserDeleteOutlined,
  UserOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { theme } from 'antd';
import type { ComponentType } from 'react';

// The catalog's fixed icon codes (the server's service_catalog domain ICONS), each drawn here
// for the console and the portal alike (QA6-PRT-01).
const DRAWN: Record<string, ComponentType> = {
  account: UserOutlined,
  access: KeyOutlined,
  laptop: LaptopOutlined,
  monitor: DesktopOutlined,
  phone: MobileOutlined,
  software: AppstoreOutlined,
  mail: MailOutlined,
  network: GlobalOutlined,
  vpn: ApiOutlined,
  printer: PrinterOutlined,
  building: BankOutlined,
  desk: HomeOutlined,
  badge: IdcardOutlined,
  people: TeamOutlined,
  document: FileTextOutlined,
  leave: CalendarOutlined,
  onboarding: UserAddOutlined,
  offboarding: UserDeleteOutlined,
  security: SafetyCertificateOutlined,
  help: QuestionCircleOutlined,
  problem: WarningOutlined,
  money: DollarOutlined,
  travel: CarOutlined,
  tools: ToolOutlined,
};

/** Whether a code has its own drawing (otherwise the general catalog icon is drawn). */
function hasCatalogIcon(code: string | null | undefined): boolean {
  return code != null && code in DRAWN;
}

/**
 * A catalog category's or item's icon on a tinted square. Decorative: the name beside it says
 * what it is, so it is hidden from screen readers.
 */
export function CatalogIcon({
  code,
  size = 40,
}: {
  code: string | null | undefined;
  size?: number;
}) {
  const { token } = theme.useToken();
  const Drawn = (code != null ? DRAWN[code] : undefined) ?? AppstoreOutlined;
  return (
    <span
      aria-hidden
      data-testid="catalog-icon"
      data-icon={hasCatalogIcon(code) ? code : 'default'}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flex: 'none',
        width: size,
        height: size,
        borderRadius: token.borderRadiusLG,
        background: token.colorPrimaryBg,
        color: token.colorPrimary,
        fontSize: Math.round(size * 0.5),
      }}
    >
      <Drawn />
    </span>
  );
}
