import type { EChartsCoreOption } from 'echarts/core';

/** The theme colours charts use for text and lines. */
export interface ChartColours {
  text: string;
  secondary: string;
  line: string;
  grid: string;
}

type Part = Record<string, unknown>;

function isPart(value: unknown): value is Part {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function each(value: unknown, change: (part: Part) => Part): unknown {
  if (Array.isArray(value)) {
    return (value as unknown[]).map((item) => (isPart(item) ? change(item) : item));
  }
  return isPart(value) ? change(value) : value;
}

function filled(part: unknown, defaults: Part): Part {
  return { ...defaults, ...(isPart(part) ? part : {}) };
}

function axis(colours: ChartColours) {
  return (part: Part): Part => ({
    ...part,
    axisLabel: filled(part.axisLabel, { color: colours.secondary }),
    axisLine: {
      ...filled(part.axisLine, {}),
      lineStyle: filled(isPart(part.axisLine) ? part.axisLine.lineStyle : undefined, {
        color: colours.line,
      }),
    },
    splitLine: {
      ...filled(part.splitLine, {}),
      lineStyle: filled(isPart(part.splitLine) ? part.splitLine.lineStyle : undefined, {
        color: colours.grid,
      }),
    },
    nameTextStyle: filled(part.nameTextStyle, { color: colours.secondary }),
  });
}

/**
 * The option with the theme's colours filled in wherever the chart left ECharts' defaults:
 * axis labels, lines and names, split lines and the legend's text. A colour the chart sets
 * itself always wins.
 */
export function withTokenColours(
  option: EChartsCoreOption,
  colours: ChartColours,
): EChartsCoreOption {
  const out: Record<string, unknown> = { ...option };
  if ('xAxis' in out) out.xAxis = each(out.xAxis, axis(colours));
  if ('yAxis' in out) out.yAxis = each(out.yAxis, axis(colours));
  if ('legend' in out) {
    out.legend = each(out.legend, (part) => ({
      ...part,
      textStyle: filled(part.textStyle, { color: colours.text }),
    }));
  }
  return out;
}
