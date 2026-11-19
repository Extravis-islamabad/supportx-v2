// The CMDB map's exports, built in the browser (WP-053 S2, REQ-CMDB-008 AC3; lane C's conditions
// 11 and 12). Pure: the screen hands over what it shows, already in words.
//
// CSV: a cell starting with = + - @, a tab or a carriage return gets a ' in front, so a
// spreadsheet never runs a CI's name as a formula (CSV injection); a UTF-8 byte order mark, so
// Arabic and Urdu open right in Excel. Only the nodes on screen go out, and a restricted one is
// the word for it with no ID.
//
// SVG: written here rather than taken from the canvas (no html-to-image). Only rect, line, text,
// g and title elements; every text XML-escaped; no foreignObject, no href, no font files, no
// event attributes, no style sheets, so the file is inert wherever it is opened.

export const CSV_BOM = '﻿';

const FORMULA_START = /^[=+\-@\t\r]/;

/** One CSV cell: formula characters defused, then quoted when it has to be. */
export function csvCell(value: string): string {
  const safe = FORMULA_START.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** A CSV file: the header row, then each row, CRLF line ends, with the BOM in front. */
export function toCsv(header: readonly string[], rows: readonly (readonly string[])[]): string {
  return CSV_BOM + [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

export interface MapCsvNode {
  restricted: boolean;
  displayId?: string;
  name?: string;
  type?: string;
  state?: string;
}

export interface MapCsvEdge {
  from: MapCsvNode;
  relationship: string;
  to: MapCsvNode;
}

export interface MapCsvWords {
  header: readonly [string, string, string, string, string, string, string, string, string];
  /** What a node the reader may not open says in every column (condition 11). */
  restricted: string;
}

const nodeCells = (node: MapCsvNode, words: MapCsvWords): string[] =>
  node.restricted
    ? [words.restricted, words.restricted, '', '']
    : [node.displayId ?? '', node.name ?? '', node.type ?? '', node.state ?? ''];

/**
 * The map's links as CSV: from (ID, name, type, state), the relationship in words, to (the same).
 * A restricted end carries the word "restricted" and nothing that identifies it.
 */
export function mapCsv(edges: readonly MapCsvEdge[], words: MapCsvWords): string {
  return toCsv(
    words.header,
    edges.map((e) => [...nodeCells(e.from, words), e.relationship, ...nodeCells(e.to, words)]),
  );
}

/** Text as XML character data or an attribute value. */
export function xmlEscape(value: string): string {
  return (
    value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&apos;')
      // Characters XML 1.0 does not allow at all (control codes) are dropped.
      // eslint-disable-next-line no-control-regex -- the point is to remove control characters
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F￾￿]/g, '')
  );
}

export interface SvgNode {
  x: number;
  y: number;
  width: number;
  height: number;
  /** The first line (the CI's name, or "A CI you can't open"). */
  title: string;
  /** The second line (type and state in words). */
  subtitle: string;
  fill: string;
  stroke: string;
  text: string;
  /** Drawn dashed: a restricted node, so it differs by shape and not by colour alone. */
  dashed?: boolean;
}

export interface SvgEdge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label: string;
}

export interface SvgMap {
  nodes: readonly SvgNode[];
  edges: readonly SvgEdge[];
  title: string;
  background: string;
  line: string;
  rtl: boolean;
}

const num = (n: number): string => String(Math.round(n * 10) / 10);
const colour = (value: string): string => (/^#[0-9a-fA-F]{3,8}$/.test(value) ? value : '#888888');

/** The map as a standalone, inert SVG file (condition 12). */
export function mapSvg(map: SvgMap): string {
  const pad = 40;
  const xs = map.nodes.flatMap((n) => [n.x, n.x + n.width]);
  const ys = map.nodes.flatMap((n) => [n.y, n.y + n.height]);
  const minX = Math.min(0, ...xs) - pad;
  const minY = Math.min(0, ...ys) - pad;
  const width = Math.max(1, ...xs) - minX + pad;
  const height = Math.max(1, ...ys) - minY + pad;
  const anchor = map.rtl ? 'end' : 'start';
  const parts: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${num(minX)} ${num(minY)} ${num(width)} ${num(height)}" width="${num(width)}" height="${num(height)}" font-family="sans-serif" direction="${map.rtl ? 'rtl' : 'ltr'}">`,
    `<title>${xmlEscape(map.title)}</title>`,
    `<rect x="${num(minX)}" y="${num(minY)}" width="${num(width)}" height="${num(height)}" fill="${colour(map.background)}"/>`,
    '<g>',
  ];
  for (const e of map.edges) {
    parts.push(
      `<line x1="${num(e.x1)}" y1="${num(e.y1)}" x2="${num(e.x2)}" y2="${num(e.y2)}" stroke="${colour(map.line)}" stroke-width="1.5"/>`,
      `<text x="${num((e.x1 + e.x2) / 2)}" y="${num((e.y1 + e.y2) / 2 - 4)}" font-size="11" text-anchor="middle" fill="${colour(map.line)}">${xmlEscape(e.label)}</text>`,
    );
  }
  for (const n of map.nodes) {
    const textX = map.rtl ? n.x + n.width - 10 : n.x + 10;
    parts.push(
      '<g>',
      `<rect x="${num(n.x)}" y="${num(n.y)}" width="${num(n.width)}" height="${num(n.height)}" rx="8" fill="${colour(n.fill)}" stroke="${colour(n.stroke)}" stroke-width="1.5"${n.dashed === true ? ' stroke-dasharray="6 4"' : ''}/>`,
      `<text x="${num(textX)}" y="${num(n.y + 26)}" font-size="13" font-weight="600" text-anchor="${anchor}" fill="${colour(n.text)}">${xmlEscape(n.title)}</text>`,
      `<text x="${num(textX)}" y="${num(n.y + 46)}" font-size="11" text-anchor="${anchor}" fill="${colour(n.text)}">${xmlEscape(n.subtitle)}</text>`,
      '</g>',
    );
  }
  parts.push('</g>', '</svg>');
  return parts.join('\n');
}
