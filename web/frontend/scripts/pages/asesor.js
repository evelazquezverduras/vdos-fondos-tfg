// asesor.js — Logica de la vista Asesor IA + Noticias.

import { api } from '../api.js';
import { store } from '../utils/store.js';
import { profileStrip } from '../components/profile-strip.js';
import { fundCard, attachVLSparkline } from '../components/fund-card.js';
import { newsCard } from '../components/news-card.js';

const HORIZONTES = ['< 1 año', '1-3 años', '3-5 años', '5-10 años', '> 10 años', 'Jubilación'];
const RENTAS = ['No declarado', '< 30.000 €', '30.000 - 60.000 €',
  '60.000 - 100.000 €', '100.000 - 200.000 €', '> 200.000 €'];
const SECTORES = ['Tecnología', 'Salud', 'Financiero', 'Energía',
  'Materias primas', 'Consumo', 'Inmobiliario', 'Renta Fija pública',
  'Renta Fija privada', 'Renta Variable global', 'ESG / Sostenibilidad'];
const REGIONES = ['España / Iberia', 'Zona Euro', 'EE.UU. / Norteamérica',
  'Reino Unido', 'Japón', 'Emergentes Asia', 'Emergentes Latinoamérica', 'Global'];
const EXCLUSIONES = ['Armas', 'Tabaco', 'Combustibles fósiles',
  'Apuestas / juego', 'Pornografía'];

function $(id) { return document.getElementById(id); }
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// ---------------------------------------------------------------------
// Render dinamico del formulario
// ---------------------------------------------------------------------
function fillSelect(selectEl, options, defaultIndex = 0) {
  selectEl.innerHTML = '';
  options.forEach((o, i) => {
    const opt = document.createElement('option');
    opt.value = o;
    opt.textContent = o;
    if (i === defaultIndex) opt.selected = true;
    selectEl.appendChild(opt);
  });
}

function makeCheckboxList(containerId, items) {
  const c = $(containerId);
  c.innerHTML = '';
  items.forEach((it) => {
    const lbl = el('label', 'form-check');
    const inp = document.createElement('input');
    inp.type = 'checkbox';
    inp.value = it;
    inp.addEventListener('change', () => {
      lbl.classList.toggle('checked', inp.checked);
    });
    lbl.appendChild(inp);
    lbl.appendChild(document.createTextNode(it));
    c.appendChild(lbl);
  });
}

function readChecks(containerId) {
  return [...$(containerId).querySelectorAll('input[type=checkbox]:checked')]
    .map((i) => i.value);
}

function setupForm() {
  fillSelect($('renta'), RENTAS, 0);
  fillSelect($('horizonte'), HORIZONTES, 3);
  makeCheckboxList('sectores', SECTORES);
  makeCheckboxList('regiones', REGIONES);
  makeCheckboxList('excluir', EXCLUSIONES);

  $('gestor-banco').value = store.getGestor();
  $('gestor-banco').addEventListener('change', (ev) => {
    store.setGestor(ev.target.value);
  });

  $('advisor-form').addEventListener('submit', onSubmit);
}

function readProfile() {
  const r = (id) => $(id).value.trim();
  const renta = $('renta').value;
  return {
    nombre: `${r('nombre')} ${r('apellidos')}`.trim() || null,
    dni: r('dni') || null,
    edad: parseInt($('edad').value, 10) || 45,
    pais: r('pais') || 'España',
    renta: renta === 'No declarado' ? null : renta,
    capital: parseInt($('capital').value, 10) || 0,
    aportacion_mensual: parseInt($('aportacion').value, 10) || 0,
    horizonte: $('horizonte').value,
    perfil_riesgo: [...document.querySelectorAll('input[name=riesgo]')]
      .find((i) => i.checked)?.value || 'Moderado',
    sectores: readChecks('sectores'),
    regiones: readChecks('regiones'),
    excluir: readChecks('excluir'),
    notas: r('notas') || null,
  };
}

// ---------------------------------------------------------------------
// Submit + render de resultados
// ---------------------------------------------------------------------
async function onSubmit(ev) {
  ev.preventDefault();
  const btn = $('btn-submit');
  const status = $('submit-status');
  const profile = readProfile();
  const gestor = $('gestor-banco').value.trim();

  btn.disabled = true;
  status.innerHTML = '<span class="spinner"></span> La IA está analizando el catálogo…';
  $('results').innerHTML = '';

  try {
    const resp = await api.advisorRecommend({
      profile,
      gestor_banco: gestor || null,
    });
    renderRecommendation(resp, profile);
    await renderNewsSection(resp.recommendation_id);
  } catch (e) {
    status.innerHTML = `<span style="color: var(--loss-700)">Error: ${e.message}</span>`;
  } finally {
    btn.disabled = false;
    if (!status.textContent.startsWith('Error')) {
      status.innerHTML = '<span style="color: var(--gain-700)">Recomendación generada.</span>';
    }
  }
}

function renderRecommendation(resp, profile) {
  const root = $('results');
  root.innerHTML = '';

  // Strip del perfil
  const strip = el('section');
  strip.appendChild(el('h2', 'mb-3', 'Perfil del inversor'));
  strip.appendChild(profileStrip(profile));
  root.appendChild(strip);

  // Resumen ejecutivo
  if (resp.resumen_ejecutivo) {
    const sec = el('section', 'card');
    sec.appendChild(el('h2', 'mb-2', 'Resumen ejecutivo'));
    sec.appendChild(el('p', '', resp.resumen_ejecutivo));
    root.appendChild(sec);
  }

  // Fondos recomendados
  if (resp.fondos_recomendados?.length) {
    const sec = el('section');
    sec.appendChild(el('h2', 'mb-3', 'Fondos recomendados'));
    const grid = el('div', 'grid grid-cols-1 lg:grid-cols-2 gap-4');
    const cards = resp.fondos_recomendados.map((f) => {
      const c = fundCard(f);
      grid.appendChild(c);
      return { isin: f.isin, el: c };
    });
    sec.appendChild(grid);
    root.appendChild(sec);
    loadSparklinesForCards(cards);
  }

  // Cartera modelo
  if (resp.cartera_modelo?.asignacion?.length) {
    const sec = el('section', 'card');
    sec.appendChild(el('h2', 'mb-2', 'Cartera modelo'));
    if (resp.cartera_modelo.descripcion) {
      sec.appendChild(el('p', 'mb-3', resp.cartera_modelo.descripcion));
    }
    const tbl = document.createElement('table');
    tbl.className = 'tbl';
    tbl.innerHTML = `
      <thead><tr><th>Bloque</th><th>Peso</th><th>ISINs</th></tr></thead>
      <tbody></tbody>`;
    const tb = tbl.querySelector('tbody');
    resp.cartera_modelo.asignacion.forEach((b) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${escapeHTML(b.bloque || '—')}</td>
        <td class="num">${Math.round(b.peso_pct || 0)} %</td>
        <td class="mono" style="font-size: 11px">${(b.isins || []).map(escapeHTML).join(', ')}</td>`;
      tb.appendChild(tr);
    });
    sec.appendChild(tbl);
    root.appendChild(sec);
  }

  // Riesgos
  if (resp.riesgos_y_advertencias) {
    const sec = el('section', 'card');
    sec.appendChild(el('h2', 'mb-2', 'Riesgos y advertencias'));
    const p = el('p', '');
    p.style.color = 'var(--loss-700)';
    p.textContent = resp.riesgos_y_advertencias;
    sec.appendChild(p);
    root.appendChild(sec);
  }
}

function escapeHTML(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

// ---------------------------------------------------------------------
// Sparklines de evolucion VL (1 ano)
// ---------------------------------------------------------------------
function oneYearRange() {
  const end = new Date();
  const start = new Date();
  start.setFullYear(end.getFullYear() - 1);
  return {
    desde: start.toISOString().slice(0, 10),
    hasta: end.toISOString().slice(0, 10),
  };
}

async function loadSparklinesForCards(cards) {
  if (!cards || cards.length === 0) return;
  const { desde, hasta } = oneYearRange();
  // En paralelo: 3-5 fondos, cada ISIN una llamada barata a SQLite.
  await Promise.all(
    cards.map(async ({ isin, el: cardEl }) => {
      if (!isin) {
        attachVLSparkline(cardEl, null);
        return;
      }
      try {
        const ts = await api.fundTimeseries(isin, { desde, hasta });
        attachVLSparkline(cardEl, ts.puntos || []);
      } catch (e) {
        attachVLSparkline(cardEl, null);
      }
    })
  );
}

// ---------------------------------------------------------------------
// Seccion de noticias
//
// Dos modos:
//   - "por_sector" (por defecto): muestra TODOS los temas derivados de la
//     recomendacion, cada uno con 4 noticias. Cada sector elegido por el
//     gestor aparece como un bloque independiente.
//   - "tema": permite profundizar en un solo tema concreto (selector +
//     termino libre).
// ---------------------------------------------------------------------
const NEWS_PER_SECTOR = 4;

async function renderNewsSection(recommendationId) {
  const root = $('results');
  const sec = el('section', 'card');
  sec.id = 'news-section';
  sec.appendChild(el('h2', 'mb-2', 'Noticias relacionadas'));
  const intro = el(
    'p',
    'text-sm mb-3',
    'Cada sector que has incluido en el perfil aparece con sus titulares más positivos.',
  );
  intro.style.color = 'var(--text-muted)';
  sec.appendChild(intro);

  let topics = [];
  try {
    topics = await api.newsTopics(recommendationId);
  } catch (e) {
    sec.appendChild(el('div', 'empty', `No se pudieron derivar temas: ${e.message}`));
    root.appendChild(sec);
    return;
  }
  if (!topics.length) {
    sec.appendChild(el('div', 'empty', 'No se han podido derivar temas relevantes.'));
    root.appendChild(sec);
    return;
  }

  // ---- Controles globales ----
  const controls = el('div', 'grid grid-cols-1 md:grid-cols-12 gap-3 mb-3');

  const modeWrap = el('div', 'md:col-span-4');
  modeWrap.appendChild(el('label', 'form-label', 'Vista'));
  const modeRow = el('div', 'form-radio-row');
  modeRow.innerHTML = `
    <span class="form-radio">
      <input type="radio" id="news-mode-sectors" name="news-mode" value="por_sector" checked />
      <label for="news-mode-sectors">Por sector</label>
    </span>
    <span class="form-radio">
      <input type="radio" id="news-mode-one" name="news-mode" value="tema" />
      <label for="news-mode-one">Un tema</label>
    </span>
  `;
  modeWrap.appendChild(modeRow);

  const classifyWrap = el('div', 'md:col-span-3 flex flex-col gap-2');
  classifyWrap.appendChild(el('label', 'form-label', 'Filtro IA'));
  const classifyLbl = el('label', 'form-check checked');
  const classifyInp = document.createElement('input');
  classifyInp.type = 'checkbox';
  classifyInp.checked = true;
  classifyInp.addEventListener('change', () => {
    classifyLbl.classList.toggle('checked', classifyInp.checked);
    refresh();
  });
  classifyLbl.appendChild(classifyInp);
  classifyLbl.appendChild(document.createTextNode('Solo positivas (IA)'));
  classifyWrap.appendChild(classifyLbl);

  // Profundizar en un tema (visible solo en modo "tema")
  const oneWrap = el('div', 'md:col-span-5 hidden', '');
  oneWrap.appendChild(el('label', 'form-label', 'Tema o término libre'));
  const oneRow = el('div', 'flex gap-2');
  const sel = document.createElement('select');
  sel.className = 'form-select';
  sel.style.maxWidth = '40%';
  topics.forEach((t) => {
    const o = document.createElement('option');
    o.value = t.query;
    o.textContent = t.label;
    sel.appendChild(o);
  });
  const free = document.createElement('option');
  free.value = '__free__';
  free.textContent = 'Otro…';
  sel.appendChild(free);
  oneRow.appendChild(sel);

  const qInp = document.createElement('input');
  qInp.className = 'form-input';
  qInp.type = 'text';
  qInp.value = topics[0].query;
  qInp.style.flex = '1';
  oneRow.appendChild(qInp);
  oneWrap.appendChild(oneRow);

  sel.addEventListener('change', () => {
    if (sel.value === '__free__') {
      qInp.value = '';
      qInp.focus();
    } else {
      qInp.value = sel.value;
    }
  });
  qInp.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); refresh(); }
  });

  controls.appendChild(modeWrap);
  controls.appendChild(classifyWrap);
  controls.appendChild(oneWrap);
  sec.appendChild(controls);

  const status = el('div', 'text-xs mb-3');
  status.style.color = 'var(--text-muted)';
  sec.appendChild(status);

  const content = el('div', 'flex flex-col gap-1');
  sec.appendChild(content);
  root.appendChild(sec);

  // ---- Lifecycle ----
  let currentMode = 'por_sector';

  modeRow.querySelectorAll('input[name=news-mode]').forEach((r) => {
    r.addEventListener('change', () => {
      currentMode = r.value;
      oneWrap.classList.toggle('hidden', currentMode !== 'tema');
      refresh();
    });
  });

  async function refresh() {
    content.innerHTML = '';
    if (currentMode === 'por_sector') {
      await loadBySector(topics, content, status, classifyInp.checked);
    } else {
      await loadSingleTopic(qInp.value.trim(), content, status, classifyInp.checked);
    }
  }

  await refresh();
}

async function loadBySector(topics, content, status, classify) {
  status.innerHTML =
    `<span class="spinner"></span> Buscando noticias en ${topics.length} sectores…`;

  // Una llamada por sector, en paralelo. El backend cachea 10 min cada query.
  const results = await Promise.all(
    topics.map(async (t) => {
      try {
        const items = await api.news(t.query, {
          classify,
          maxResults: NEWS_PER_SECTOR,
        });
        return { topic: t, items, error: null };
      } catch (e) {
        return { topic: t, items: [], error: e.message || String(e) };
      }
    })
  );

  const totalItems = results.reduce((acc, r) => acc + r.items.length, 0);
  status.textContent =
    `${results.length} sector(es) · ${totalItems} titulares en total` +
    (classify ? ' (priorizando positivos)' : '');

  results.forEach(({ topic, items, error }) => {
    const block = el('section', 'news-sector-block');

    const head = el('div', 'news-sector-header');
    head.appendChild(el('div', 'news-sector-title', topic.label));
    head.appendChild(el(
      'div',
      'news-sector-meta',
      items.length ? `${items.length} titular(es)` : 'sin titulares',
    ));
    block.appendChild(head);

    if (error) {
      block.appendChild(el('div', 'news-sector-empty', `Error: ${error}`));
    } else if (items.length === 0) {
      block.appendChild(el('div', 'news-sector-empty', 'No se encontraron noticias para este sector.'));
    } else {
      const list = el('div', 'flex flex-col gap-2');
      items.forEach((it) => list.appendChild(newsCard(it)));
      block.appendChild(list);
    }
    content.appendChild(block);
  });
}

async function loadSingleTopic(query, content, status, classify) {
  if (!query) {
    status.innerHTML =
      `<span style="color: var(--loss-700)">Introduce un término de búsqueda.</span>`;
    return;
  }
  status.innerHTML =
    `<span class="spinner"></span> Buscando noticias sobre «${escapeHTML(query)}»…`;
  try {
    const items = await api.news(query, { classify, maxResults: 6 });
    status.textContent = `${items.length} resultado(s)`;
    if (!items.length) {
      content.appendChild(el('div', 'empty', 'Sin resultados.'));
      return;
    }
    const list = el('div', 'flex flex-col gap-2');
    items.forEach((it) => list.appendChild(newsCard(it)));
    content.appendChild(list);
  } catch (e) {
    status.innerHTML =
      `<span style="color: var(--loss-700)">No se pudieron obtener noticias: ${escapeHTML(e.message)}</span>`;
  }
}

setupForm();
