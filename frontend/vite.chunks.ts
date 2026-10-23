/**
 * Vendor chunk groups for production builds (Rolldown `codeSplitting`, Vite 8). Libraries change
 * far less often than app code, so separate chunks stay in the browser cache across releases,
 * and no single chunk carries all of Ant Design, React and i18n at once (WP-010: the old
 * single bundle was 726 kB). Pages are split separately by the router's lazy routes.
 */
const pkg = (names: string) => new RegExp(`[\\\\/]node_modules[\\\\/](${names})[\\\\/]`);

export const codeSplitting = {
  groups: [
    {
      name: 'vendor-react',
      test: pkg('react|react-dom|scheduler|react-router|cookie|set-cookie-parser'),
      priority: 30,
    },
    // Ant Design's data-entry/display components (tables, forms, pickers) apart from the rest.
    {
      name: 'vendor-antd-data',
      test: /[\\/]node_modules[\\/]antd[\\/](es|lib)[\\/](table|pagination|form|tree|tree-select|date-picker|time-picker|calendar|select|auto-complete|cascader|transfer|upload|color-picker|input-number|mentions|descriptions|list)[\\/]/,
      priority: 15,
    },
    { name: 'vendor-antd', test: pkg('antd'), priority: 10 },
    {
      name: 'vendor-antd-parts',
      test: pkg(
        'rc-[^/\\\\]+|@rc-component[\\\\/][^/\\\\]+|@ant-design[\\\\/][^/\\\\]+|dayjs|@babel[\\\\/]runtime|classnames|stylis|@emotion[\\\\/][^/\\\\]+|compute-scroll-into-view|scroll-into-view-if-needed|throttle-debounce|json2mq|copy-to-clipboard|toggle-selection|string-convert|resize-observer-polyfill',
      ),
      priority: 20,
    },
    {
      name: 'vendor-i18n',
      test: pkg('i18next|react-i18next|html-parse-stringify|void-elements'),
      priority: 20,
    },
    { name: 'vendor-data', test: pkg('@tanstack[\\\\/][^/\\\\]+|openapi-fetch'), priority: 20 },
    {
      name: 'vendor-forms',
      test: pkg('react-hook-form|zod|@hookform[\\\\/][^/\\\\]+'),
      priority: 20,
    },
    { name: 'vendor-echarts', test: pkg('echarts|zrender|tslib'), priority: 20 },
  ],
};
