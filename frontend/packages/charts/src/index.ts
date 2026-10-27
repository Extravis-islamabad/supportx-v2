// @supportx/charts: Apache ECharts wrapper (WP-010) and the chart kit shared by reports and
// dashboard widgets (WP-035, REQ-RPT-044; architecture.md §9.6).
export { Chart, type ChartProps } from './Chart';
export { mirrorForRtl } from './rtl';
export type { EChartsCoreOption } from 'echarts/core';
export { kitOption, LARGE_SERIES, type KitChartType, type KitInput, type KitSeries } from './kit';
