// profile-strip.js — 4 metric cards horizontales con el perfil del cliente.

import { fmtEUR } from '../utils/format.js';

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function card(label, value, help) {
  const c = el('div', 'metric-card');
  c.appendChild(el('div', 'metric-label', label));
  c.appendChild(el('div', 'metric-value', value));
  if (help) c.appendChild(el('div', 'metric-help', help));
  return c;
}

export function profileStrip(profile) {
  const wrap = el('div', 'profile-strip');
  wrap.appendChild(
    card('Edad', profile.edad ?? '—', profile.pais || '')
  );
  wrap.appendChild(
    card('Riesgo', profile.perfil_riesgo || '—', profile.horizonte || '')
  );
  wrap.appendChild(
    card('Capital', fmtEUR(profile.capital), profile.aportacion_mensual
      ? `+${fmtEUR(profile.aportacion_mensual)}/mes`
      : 'sin aportaciones'
    )
  );
  const preferencias =
    [...(profile.sectores || []), ...(profile.regiones || [])]
      .slice(0, 2)
      .join(' · ') || '—';
  wrap.appendChild(
    card('Preferencias', preferencias.length > 24
      ? preferencias.slice(0, 23) + '…'
      : preferencias,
      (profile.excluir || []).length ? `excluye: ${profile.excluir.join(', ')}` : '')
  );
  return wrap;
}
