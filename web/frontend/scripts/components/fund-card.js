// fund-card.js — Card de un fondo recomendado.

import { chipRow } from './chip.js';
import { citation } from './citation.js';
import { sparkline, returnPct } from './sparkline.js';

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function metric(label, value) {
  const wrap = el('div', 'fund-metric');
  wrap.appendChild(el('div', 'lbl', label));
  wrap.appendChild(el('div', 'val', value || '—'));
  return wrap;
}

export function fundCard(fund) {
  const card = el('article', 'fund-card');
  card.dataset.isin = fund.isin || '';

  // Head: gestora · ISIN, nombre, score
  const head = el('div', 'fund-card-head');
  const left = el('div');
  const meta = `${fund.gestora || '—'} · ${fund.isin}`;
  left.appendChild(el('div', 'fund-meta', meta));
  left.appendChild(el('div', 'fund-name', fund.nombre || '(sin nombre)'));
  head.appendChild(left);

  const score = el('div', 'score-pill');
  const num = el('div', 'num');
  num.textContent = `${Math.round(fund.peso_cartera_pct || 0)}%`;
  score.appendChild(num);
  score.appendChild(el('div', 'lbl', 'peso cartera'));
  head.appendChild(score);
  card.appendChild(head);

  // Chips P00/P05/P06 + ASG / garantizado
  const chips = [];
  if (fund.chips?.p00) chips.push({ text: fund.chips.p00, variant: 'p00' });
  if (fund.chips?.p05) chips.push({ text: fund.chips.p05, variant: 'p05' });
  if (fund.chips?.p06) chips.push({ text: fund.chips.p06, variant: 'p06' });
  if (fund.metricas?.garantizado) {
    chips.push({ text: 'garantizado', variant: 'sector' });
  }
  if (chips.length) card.appendChild(chipRow(chips));

  // Bloque de evolucion VL (sparkline). Lo deja como placeholder a la
  // espera de attachVLSparkline() o similar. Si no hay datos para el ISIN
  // (fondo no en CSV de VL), se queda con el mensaje de fallback.
  const vlBlock = el('div', 'fund-vl-block');
  vlBlock.dataset.role = 'vl-block';
  vlBlock.innerHTML = `
    <div class="fund-vl-head">
      <span class="fund-vl-label">Evolución VL (1 año)</span>
      <span class="fund-vl-return mono" data-role="vl-return">—</span>
    </div>
    <div class="fund-vl-chart" data-role="vl-chart">
      <span class="spinner"></span>
      <span class="fund-vl-loading">cargando…</span>
    </div>
  `;
  card.appendChild(vlBlock);

  // Grid de metricas. Comisiones desde la misma fuente que la justificacion
  // (CSV VDOS) -> gestion <= total siempre coherente.
  const grid = el('div', 'fund-metrics');
  grid.appendChild(metric('Comisión gestión', fund.metricas?.comision_gestion));
  grid.appendChild(metric('Comisión total', fund.metricas?.comision_total));
  grid.appendChild(metric('Plazo recomendado', fund.metricas?.plazo_recomendado));
  // Riesgo 1-7: del folleto (PRIESGOF) si existe; si no, derivado de la
  // volatilidad (SRRI). Se etiqueta para no confundir ambas fuentes.
  const riesgoLabel = fund.metricas?.riesgo_fuente === 'vol'
    ? 'Riesgo (vol.)' : 'Riesgo CNMV';
  grid.appendChild(metric(
    riesgoLabel,
    fund.metricas?.riesgo ? `${fund.metricas.riesgo} / 7` : '—'
  ));
  grid.appendChild(metric(
    'Garantía',
    fund.metricas?.garantizado ? 'Sí' : 'No'
  ));
  card.appendChild(grid);

  // Justificacion (citation block)
  if (fund.justificacion) {
    card.appendChild(citation(fund.justificacion, fund.provenance));
  }

  return card;
}

/**
 * Rellena el bloque VL de una card con la serie ya descargada.
 * Si la serie no es valida, deja un mensaje 'sin historico'.
 */
export function attachVLSparkline(cardEl, puntos) {
  if (!cardEl) return;
  const chart = cardEl.querySelector('[data-role="vl-chart"]');
  const retEl = cardEl.querySelector('[data-role="vl-return"]');
  if (!chart) return;
  chart.innerHTML = '';

  const sl = sparkline(puntos || []);
  if (!sl) {
    chart.innerHTML = '<span class="fund-vl-empty">sin histórico disponible</span>';
    if (retEl) retEl.textContent = '—';
    return;
  }
  chart.appendChild(sl);

  const r = returnPct(puntos);
  if (r === null) {
    if (retEl) retEl.textContent = '—';
    return;
  }
  const sign = r >= 0 ? '+' : '';
  retEl.textContent = `${sign}${r.toFixed(2)} %`;
  retEl.classList.toggle('is-gain', r >= 0);
  retEl.classList.toggle('is-loss', r < 0);
}
