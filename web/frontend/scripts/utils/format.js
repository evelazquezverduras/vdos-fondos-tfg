// format.js — Formato es-ES para porcentajes, EUR, fechas y numeros.

const NF_INT = new Intl.NumberFormat('es-ES');
const NF_EUR = new Intl.NumberFormat('es-ES', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
});
const NF_PCT = new Intl.NumberFormat('es-ES', {
  style: 'percent',
  maximumFractionDigits: 2,
});

export function fmtInt(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return NF_INT.format(n);
}

export function fmtEUR(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return NF_EUR.format(n);
}

export function fmtPct(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return NF_PCT.format(n);
}

export function truncate(s, max = 32) {
  if (!s) return '';
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}
