// citation.js — Bloque de justificacion: cita serif sobre azul-50 + provenance mono.

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export function citation(text, provenance) {
  const wrap = el('div', 'citation-block');
  const t = el('p', 'citation-text');
  t.textContent = text || '';
  wrap.appendChild(t);
  if (provenance) {
    wrap.appendChild(el('div', 'citation-provenance', provenance));
  }
  return wrap;
}
