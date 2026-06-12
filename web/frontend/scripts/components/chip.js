// chip.js — Render de chip de categorizacion (P00/P05/P06/sector).

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export function chip(text, variant = 'neutral') {
  if (!text) return null;
  const classes = {
    p00: 'chip chip-p00',
    p05: 'chip chip-p05',
    p06: 'chip chip-p06',
    sector: 'chip chip-sector',
    neutral: 'chip',
  };
  return el('span', classes[variant] || 'chip', text);
}

export function chipRow(items) {
  // items: [{ text, variant }, ...]
  const wrap = el('div', 'flex flex-wrap items-center gap-1.5');
  for (const { text, variant } of items) {
    const c = chip(text, variant);
    if (c) wrap.appendChild(c);
  }
  return wrap;
}
