// sparkline.js — Mini-chart SVG vanilla, sin dependencias.
//
// Pinta una serie [{ fecha, vl }] en un SVG ligero. Pensado para las cards
// del Asesor IA (~120 x 32 px). Sin tooltips ni interactividad: es un
// indicador visual de tendencia, no un grafico de analisis.

const W = 160;
const H = 40;
const PAD_X = 2;
const PAD_Y = 3;

function buildPath(points, width, height) {
  if (points.length < 2) return '';
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xmin = Math.min(...xs);
  const xmax = Math.max(...xs);
  const ymin = Math.min(...ys);
  const ymax = Math.max(...ys);
  const xrange = xmax - xmin || 1;
  const yrange = ymax - ymin || 1;

  const usableW = width - 2 * PAD_X;
  const usableH = height - 2 * PAD_Y;

  return points
    .map((p, i) => {
      const x = PAD_X + ((p.x - xmin) / xrange) * usableW;
      const y = PAD_Y + (1 - (p.y - ymin) / yrange) * usableH;
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
}

/**
 * Pinta un sparkline a partir de una serie de puntos {fecha, vl}.
 *
 * @param {Array<{fecha: string, vl: number}>} puntos - Serie ascendente por fecha.
 * @param {Object} opts
 * @param {number} [opts.width=160]
 * @param {number} [opts.height=40]
 * @returns {SVGSVGElement|null} - null si menos de 2 puntos validos.
 */
export function sparkline(puntos, opts = {}) {
  if (!Array.isArray(puntos) || puntos.length < 2) return null;
  const valid = puntos
    .map((p, i) => ({ x: i, y: Number(p.vl) }))
    .filter((p) => Number.isFinite(p.y));
  if (valid.length < 2) return null;

  const width = opts.width || W;
  const height = opts.height || H;

  const first = valid[0].y;
  const last = valid[valid.length - 1].y;
  const goingUp = last >= first;
  const stroke = goingUp ? 'var(--gain-700)' : 'var(--loss-700)';
  const fillStop = goingUp ? 'var(--gain-50)' : 'var(--loss-50)';

  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', String(width));
  svg.setAttribute('height', String(height));
  svg.setAttribute('class', 'sparkline');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `Evolución VL`);

  // Area suave (relleno bajo la curva)
  const linePath = buildPath(valid, width, height);
  const xs = valid.map((p) => p.x);
  const xmin = Math.min(...xs);
  const xmax = Math.max(...xs);
  const xrange = xmax - xmin || 1;
  const usableW = width - 2 * PAD_X;
  const x0 = PAD_X + ((valid[0].x - xmin) / xrange) * usableW;
  const xN = PAD_X + ((valid[valid.length - 1].x - xmin) / xrange) * usableW;
  const areaPath = `${linePath} L ${xN.toFixed(2)} ${height - PAD_Y} L ${x0.toFixed(2)} ${height - PAD_Y} Z`;

  const area = document.createElementNS(ns, 'path');
  area.setAttribute('d', areaPath);
  area.setAttribute('fill', fillStop);
  area.setAttribute('opacity', '0.6');
  svg.appendChild(area);

  const line = document.createElementNS(ns, 'path');
  line.setAttribute('d', linePath);
  line.setAttribute('fill', 'none');
  line.setAttribute('stroke', stroke);
  line.setAttribute('stroke-width', '1.5');
  line.setAttribute('stroke-linecap', 'round');
  line.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(line);

  // Punto final
  const dot = document.createElementNS(ns, 'circle');
  const lastP = valid[valid.length - 1];
  const usableH = height - 2 * PAD_Y;
  const ys = valid.map((p) => p.y);
  const ymin = Math.min(...ys);
  const ymax = Math.max(...ys);
  const yrange = ymax - ymin || 1;
  const lastY = PAD_Y + (1 - (lastP.y - ymin) / yrange) * usableH;
  dot.setAttribute('cx', xN.toFixed(2));
  dot.setAttribute('cy', lastY.toFixed(2));
  dot.setAttribute('r', '2');
  dot.setAttribute('fill', stroke);
  svg.appendChild(dot);

  return svg;
}

/**
 * Calcula la rentabilidad acumulada (%) sobre la serie de VL.
 * Devuelve null si la serie es invalida.
 */
export function returnPct(puntos) {
  if (!Array.isArray(puntos) || puntos.length < 2) return null;
  const valid = puntos.map((p) => Number(p.vl)).filter(Number.isFinite);
  if (valid.length < 2 || valid[0] === 0) return null;
  return (valid[valid.length - 1] / valid[0] - 1) * 100;
}
