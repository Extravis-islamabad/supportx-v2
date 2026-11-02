import type { EChartsCoreOption } from 'echarts/core';

// One chart kit for reports and dashboard widgets (REQ-RPT-044): the same data gives the same
// chart type, order and colours wherever it is shown. Pure (no DOM), so it is unit-tested and the
// server can mirror it for PDF exports later. Knows nothing about reports: callers pass labelled
// categories and series.

export type KitChartType = 'bar' | 'stacked_bar' | 'line' | 'area' | 'doughnut' | 'gauge';

export interface KitSeries {
  /** Already translated. */
  name: string;
  values: (number | null)[];
}

export interface KitInput {
  type: KitChartType;
  /** Category labels along the axis (or slices), already translated. */
  categories: string[];
  series: KitSeries[];
  /**
   * A fixed colour per category (e.g. P1 is always the same red), or undefined to use the theme's
   * order. Used for single-series bars and doughnut slices.
   */
  categoryColors?: (string | undefined)[];
  /** Formats a value for tooltips and labels (units, percent, durations), already localised. */
  format?: (value: number) => string;
  /** Gauge only: the maximum (100 for percentages). */
  max?: number;
  /**
   * A narrow place (a dashboard widget of 4 columns or less): a doughnut leaves the names to its
   * legend, which wraps, instead of slice labels cut to "P…" (QA WP-036 C1).
   */
  compact?: boolean;
}

/** Longest category name shown on an axis or slice label; the tooltip and table show it whole. */
export const LABEL_MAX = 24;

/**
 * `text` shortened in the middle ("QA35 789…Support Beta"), so names that differ only at the end
 * stay apart (QA WP-035 BUG-06). Counts what readers see as one character (grapheme), so an
 * Arabic letter keeps its marks.
 */
const graphemes = new Intl.Segmenter(undefined, { granularity: 'grapheme' });

export function middleEllipsis(text: string, max = LABEL_MAX): string {
  const chars = Array.from(graphemes.segment(text), (part) => part.segment);
  if (chars.length <= max) return text;
  const head = Math.floor((max - 1) / 2);
  const tail = max - 1 - head;
  return `${chars.slice(0, head).join('')}…${chars.slice(chars.length - tail).join('')}`;
}

const shortLabel = (value: string | number) => middleEllipsis(String(value));

/** Above this many points a line or area chart samples (LTTB) so the page never freezes. */
export const LARGE_SERIES = 2_000;

function valueTooltip(format: KitInput['format']) {
  return format === undefined
    ? undefined
    : (value: unknown) => (typeof value === 'number' ? format(value) : '');
}

/** The ECharts option for `input` (ECharts' own theme and RTL are applied by `<Chart>`). */
export function kitOption(input: KitInput): EChartsCoreOption {
  const format = valueTooltip(input.format);
  if (input.type === 'doughnut') {
    const first = input.series[0]?.values ?? [];
    return {
      tooltip: { trigger: 'item', valueFormatter: format },
      legend: { type: input.compact === true ? 'plain' : 'scroll', bottom: 0 },
      series: [
        {
          type: 'pie',
          // Up and a little smaller, so the slices never reach the legend row (QA BUG-03).
          center: ['50%', '44%'],
          radius: ['40%', '64%'],
          avoidLabelOverlap: true,
          label: {
            show: input.compact !== true,
            formatter: (params: { name: string }) => shortLabel(params.name),
          },
          data: input.categories.map((name, i) => ({
            name,
            value: first[i] ?? 0,
            itemStyle: input.categoryColors?.[i] ? { color: input.categoryColors[i] } : undefined,
          })),
        },
      ],
    };
  }
  if (input.type === 'gauge') {
    const value = input.series[0]?.values[0] ?? 0;
    return {
      tooltip: { show: false },
      series: [
        {
          type: 'gauge',
          min: 0,
          max: input.max ?? 100,
          progress: { show: true },
          detail: { valueAnimation: false, formatter: format ?? '{value}' },
          data: [{ value, name: input.series[0]?.name ?? '' }],
        },
      ],
    };
  }
  const line = input.type === 'line' || input.type === 'area';
  const large = input.categories.length > LARGE_SERIES;
  const single = input.series.length === 1;
  return {
    tooltip: { trigger: 'axis', valueFormatter: format },
    legend: single ? undefined : { type: 'scroll', bottom: 0 },
    grid: { left: 8, right: 8, top: 16, bottom: single ? 8 : 40, containLabel: true },
    xAxis: {
      type: 'category',
      data: input.categories,
      axisLabel: { hideOverlap: true, formatter: shortLabel },
    },
    yAxis: { type: 'value', axisLabel: format ? { formatter: format } : undefined },
    series: input.series.map((s) => ({
      name: s.name,
      type: line ? 'line' : 'bar',
      stack: input.type === 'stacked_bar' ? 'total' : undefined,
      areaStyle: input.type === 'area' ? {} : undefined,
      showSymbol: line && !large,
      sampling: line && large ? 'lttb' : undefined,
      large: !line && large,
      data:
        single && !line && input.categoryColors
          ? s.values.map((value, i) => ({
              value,
              itemStyle: input.categoryColors?.[i] ? { color: input.categoryColors[i] } : undefined,
            }))
          : s.values,
    })),
  };
}
