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
// tooltip. Colours from the design target; every icon is at least 3:1 on its tint (measured
// in channel.test.ts).

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

export interface Look {
  icon: ReactNode;
  bg: string;
  fg: string;
}

const MAIL = { bg: '#EEF4FF', fg: '#3538CD' };
const VOICE = { bg: '#ECFDF3', fg: '#067647' };
const WEB = { bg: '#F4EBFF', fg: '#6B33B8' };
const ALERT = { bg: '#FEF3F2', fg: '#B42318' };
const PERSON = { bg: '#F2F4F7', fg: '#475467' };
const CHAT = { bg: '#ECFDFF', fg: '#0E7090' };
const SYSTEM = { bg: '#FFF6ED', fg: '#B93815' };

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
