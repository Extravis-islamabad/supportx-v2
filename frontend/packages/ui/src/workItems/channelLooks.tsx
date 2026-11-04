import {
  ApiOutlined,
  CommentOutlined,
  GlobalOutlined,
  MailOutlined,
  MessageOutlined,
  MobileOutlined,
  NotificationOutlined,
  PhoneOutlined,
  RobotOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';

// Where a work item came from (REQ-INC-005), shown on every list row and the record header
// (UI pass 2). Each channel has an icon, a tint and its label as the accessible name and
// tooltip. Colours from the design target; in dark mode a deep tint of the same hue with a
// light icon, so no light chip sits on the dark page. Every icon is at least 4.5:1 on its tint
// in both (measured in channel.test.ts).

/** The pulse of a monitoring alert (MonetX): drawn here, no icon set has a neutral one. */
const PULSE_ICON = (
  <svg
    width="1em"
    height="1em"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden
    focusable="false"
  >
    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </svg>
);

export interface Tint {
  bg: string;
  fg: string;
}

export interface Look extends Tint {
  icon: ReactNode;
  /** The same channel on the dark theme. */
  dark: Tint;
}

const MAIL = { bg: '#EEF4FF', fg: '#3538CD', dark: { bg: '#1F235B', fg: '#A4BCFD' } };
const VOICE = { bg: '#ECFDF3', fg: '#067647', dark: { bg: '#053321', fg: '#75E0A7' } };
const WEB = { bg: '#F4EBFF', fg: '#6B33B8', dark: { bg: '#2C1C5F', fg: '#D6BBFB' } };
const ALERT = { bg: '#FEF3F2', fg: '#B42318', dark: { bg: '#55160C', fg: '#FDA29B' } };
const PERSON = { bg: '#F2F4F7', fg: '#475467', dark: { bg: '#1F242F', fg: '#CECFD2' } };
const CHAT = { bg: '#ECFDFF', fg: '#0E7090', dark: { bg: '#0D2D3A', fg: '#67E3F9' } };
const SYSTEM = { bg: '#FFF6ED', fg: '#B93815', dark: { bg: '#511C10', fg: '#FEB273' } };

export const CHANNEL_LOOKS: Record<string, Look> = {
  email: { icon: <MailOutlined />, ...MAIL },
  phone: { icon: <PhoneOutlined />, ...VOICE },
  portal: { icon: <GlobalOutlined />, ...WEB },
  monetx: { icon: PULSE_ICON, ...ALERT },
  alert_webhook: { icon: <NotificationOutlined />, ...ALERT },
  walk_up: { icon: <UserOutlined />, ...PERSON },
  chat: { icon: <MessageOutlined />, ...CHAT },
  virtual_agent: { icon: <RobotOutlined />, ...CHAT },
  teams: { icon: <TeamOutlined />, ...CHAT },
  slack: { icon: <CommentOutlined />, ...CHAT },
  whatsapp: { icon: <MessageOutlined />, ...CHAT },
  mobile_app: { icon: <MobileOutlined />, ...WEB },
  api: { icon: <ApiOutlined />, ...SYSTEM },
};

export const FALLBACK_LOOK: Look = { icon: <GlobalOutlined />, ...PERSON };
