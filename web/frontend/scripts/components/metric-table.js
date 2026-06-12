// metric-table.js — Tabla comparativa A | B con semaforo "mejor".
//
// API:
//   renderMetricTable(container, { title, rows })
//
//   rows: [{
//     label: string,
//     a: number|string|null,
//     b: number|string|null,
//     fmt: 'pct'|'pct4'|'num'|'num4'|'eur_k'|'int'|'str',
//     better: 'higher'|'lower'|null   // pinta verde el mejor
//   }, ...]

import { fmtPct } from '../utils/format.js';

const NF_NUM_4 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 4 });
const NF_NUM_2 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 });
const NF_INT = new Intl.NumberFormat('es-ES');
const NF_PCT_2 = new Intl.NumberFormat('es-ES', {
  style: 'percent',
  maximumFractionDigits: 2,
});
const NF_PCT_4 = new Intl.NumberFormat('es-ES', {
  style: 'percent',
  maximumFractionDigits: 4,
});

function fmtValue(v, fmt) {
  if (v === null || v === undefined || Number.isNaN(v) || v === '') return '—';
  switch (fmt) {
    case 'pct':
      return typeof v === 'number' ? NF_PCT_2.format(v) : v;
    case 'pct4':
      return typeof v === 'number' ? NF_PCT_4.format(v) : v;
    case 'num':
      return typeof v === 'number' ? NF_NUM_2.format(v) : v;
    case 'num4':
      return typeof v === 'number' ? NF_NUM_4.format(v) : v;
    case 'eur_k':
      // patrimonio en miles
      if (typeof v !== 'number') return v;
      return new Intl.NumberFormat('es-ES', {
        style: 'currency',
        currency: 'EUR',
        maximumFractionDigits: 0,
      }).format(v * 1000);
    case 'int':
      return typeof v === 'number' ? NF_INT.format(v) : v;
    case 'str':
    default:
      return String(v);
  }
}

function diffBetter(a, b, better) {
  if (better === null || better === undefined) return [false, false];
  if (typeof a !== 'number' || typeof b !== 'number') return [false, false];
  if (a === b) return [false, false];
  if (better === 'higher') return [a > b, b > a];
  if (better === 'lower') return [a < b, b < a];
  return [false, false];
}

export function renderMetricTable(container, { title, rows }) {
  container.innerHTML = '';

  if (title) {
    const h = document.createElement('h3');
    h.className = 'metric-table-title';
    h.textContent = title;
    container.appendChild(h);
  }

  const table = document.createElement('table');
  table.className = 'metric-table';

  const thead = document.createElement('thead');
  thead.innerHTML = `
    <tr>
      <th scope="col">Métrica</th>
      <th scope="col" class="col-a">A</th>
      <th scope="col" class="col-b">B</th>
    </tr>
  `;
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr');
    const [aBetter, bBetter] = diffBetter(row.a, row.b, row.better);
    tr.innerHTML = `
      <td class="lbl">${row.label}</td>
      <td class="val mono col-a ${aBetter ? 'is-better' : ''}">${fmtValue(row.a, row.fmt)}</td>
      <td class="val mono col-b ${bBetter ? 'is-better' : ''}">${fmtValue(row.b, row.fmt)}</td>
    `;
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);
}
