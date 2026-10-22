import type { ThemeConfig } from 'antd';

// Brand seed tokens. Ant Design defaults for now (D-008); per-tenant branding arrives with the
// design system work. Every theme (light, dark, high contrast later) derives from these seeds.
export const brandTokens: ThemeConfig['token'] = {
  colorPrimary: '#1668dc',
  borderRadius: 6,
};
