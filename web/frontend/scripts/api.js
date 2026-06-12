// api.js — Wrappers fetch sobre la API FastAPI.
// Mismo origen por defecto; PUBLIC_API_BASE permite proxy en produccion.

const API_BASE = window.__VDOS_API_BASE__ || '';

async function request(path, { method = 'GET', headers = {}, body, expert = false } = {}) {
  const h = { 'Content-Type': 'application/json', ...headers };
  if (expert) h['X-Modo-Experto'] = '1';

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: h,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail;
    try {
      const j = await res.json();
      detail = j.detail || j.message || JSON.stringify(j);
    } catch {
      detail = await res.text();
    }
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }

  return res.json();
}

export const api = {
  health: () => request('/api/health'),
  stats: (opts) => request('/api/stats', opts),
  distribucionCategoria: (opts) => request('/api/distribucion/categoria', opts),
  distribucionGestora: (limit = 20, opts) =>
    request(`/api/distribucion/gestora?limit=${limit}`, opts),
  indexStatus: () => request('/api/index/status'),

  // Asesor
  advisorRecommend: (body, opts) =>
    request('/api/advisor/recommend', { method: 'POST', body, ...(opts || {}) }),

  // Noticias
  newsTopics: (recommendationId) =>
    request(`/api/news/topics?from_recommendation_id=${encodeURIComponent(recommendationId)}`),
  news: (topic, { classify = true, maxResults = 5 } = {}) => {
    const qs = new URLSearchParams({
      topic,
      classify: classify ? 'true' : 'false',
      max_results: String(maxResults),
    });
    return request(`/api/news?${qs.toString()}`);
  },

  // Comparador
  fundFilters: () => request('/api/funds/filters'),
  fundSearch: ({ q, tipo, gestora, onlyWithBrochure = false, limit = 20 } = {}) => {
    const qs = new URLSearchParams();
    if (q) qs.set('q', q);
    if (tipo) qs.set('tipo', tipo);
    if (gestora) qs.set('gestora', gestora);
    if (onlyWithBrochure) qs.set('only_with_brochure', 'true');
    qs.set('limit', String(limit));
    return request(`/api/funds/search?${qs.toString()}`);
  },
  fundDetail: (isin) => request(`/api/funds/${encodeURIComponent(isin)}`),
  fundTimeseries: (isin, { desde, hasta } = {}) => {
    const qs = new URLSearchParams();
    if (desde) qs.set('desde', desde);
    if (hasta) qs.set('hasta', hasta);
    const tail = qs.toString() ? `?${qs.toString()}` : '';
    return request(`/api/funds/${encodeURIComponent(isin)}/timeseries${tail}`);
  },
  compare: (body) => request('/api/compare', { method: 'POST', body }),
  compareSummary: (body) => request('/api/compare/summary', { method: 'POST', body }),

  // Estudio comparativo VDOS vs ChatGPT
  estudioPerfiles: () => request('/api/estudio/perfiles'),
  estudioPerfil: (id) => request(`/api/estudio/perfil/${encodeURIComponent(id)}`),
  estudioComparativa: (id) => request(`/api/estudio/perfil/${encodeURIComponent(id)}/comparativa`),
  estudioRunAsesor: (id) =>
    request(`/api/estudio/perfil/${encodeURIComponent(id)}/run-asesor`, { method: 'POST', body: {} }),
  estudioPasteChatGPT: (id, body) =>
    request(`/api/estudio/perfil/${encodeURIComponent(id)}/chatgpt-paste`, {
      method: 'POST',
      body,
    }),
  estudioDeleteChatGPT: (id) =>
    request(`/api/estudio/perfil/${encodeURIComponent(id)}/chatgpt`, { method: 'DELETE' }),
  estudioAgregado: () => request('/api/estudio/agregado'),
  estudioPanelAvanzado: (id) =>
    request(`/api/estudio/perfil/${encodeURIComponent(id)}/panel-avanzado`),
};
