// plot.js — Wrapper minimo sobre Plotly con la paleta VDOS.

const VDOS = {
  900: '#042C53',
  700: '#0C447C',
  500: '#185FA5',
  400: '#378ADD',
  100: '#B5D4F4',
  50:  '#E6F1FB',
  border: 'rgba(0,0,0,0.08)',
  muted: '#5F5E5A',
};

const BASE_LAYOUT = {
  font: { family: 'Inter, system-ui, sans-serif', size: 12, color: VDOS[900] },
  paper_bgcolor: '#FFFFFF',
  plot_bgcolor: '#FFFFFF',
  margin: { l: 50, r: 16, t: 8, b: 80 },
  showlegend: false,
  xaxis: {
    tickangle: -35,
    tickfont: { size: 11, color: VDOS.muted },
    gridcolor: VDOS.border,
    linecolor: VDOS.border,
    zerolinecolor: VDOS.border,
  },
  yaxis: {
    tickfont: { size: 11, color: VDOS.muted },
    gridcolor: VDOS.border,
    linecolor: VDOS.border,
    zerolinecolor: VDOS.border,
  },
};

const CONFIG = {
  responsive: true,
  displayModeBar: false,
  locale: 'es',
};

function ensurePlotly() {
  if (typeof window.Plotly === 'undefined') {
    throw new Error('Plotly no esta cargado. Revisa la etiqueta <script> del CDN.');
  }
}

export function barChart(target, items, { color = VDOS[500], hoverPrefix = '' } = {}) {
  ensurePlotly();
  const el = typeof target === 'string' ? document.getElementById(target) : target;
  if (!el) return;

  const labels = items.map((i) => i.label);
  const values = items.map((i) => i.count);

  const trace = {
    type: 'bar',
    x: labels,
    y: values,
    marker: { color, line: { width: 0 } },
    hovertemplate: `${hoverPrefix}%{x}<br><b>%{y}</b> ISINs<extra></extra>`,
  };

  window.Plotly.newPlot(el, [trace], BASE_LAYOUT, CONFIG);
}
