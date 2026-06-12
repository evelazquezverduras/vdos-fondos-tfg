// fund-search.js — Autocomplete de fondos sobre /api/funds/search.
//
// API publica:
//   mountFundSearch({ inputEl, dropdownEl, label, getFilters, onSelect })
//     - inputEl: <input> donde el usuario escribe
//     - dropdownEl: <div> contenedor de resultados (oculto por defecto)
//     - label: 'A' o 'B' (para aria)
//     - getFilters: () => ({ tipo, gestora, onlyWithBrochure })
//     - onSelect: (hit) => void   // hit = { isin, nombre, gestora, has_brochure }

import { api } from '../api.js';

const DEBOUNCE_MS = 200;
const MIN_CHARS = 0; // permitimos lista inicial vacia

export function mountFundSearch({ inputEl, dropdownEl, label, getFilters, onSelect }) {
  let timer = null;
  let lastQuery = null;
  let currentHits = [];
  let active = -1;

  const close = () => {
    dropdownEl.classList.add('hidden');
    active = -1;
  };
  const open = () => {
    dropdownEl.classList.remove('hidden');
  };

  const render = (hits) => {
    dropdownEl.innerHTML = '';
    if (hits.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'fund-search-empty';
      empty.textContent = 'Sin resultados';
      dropdownEl.appendChild(empty);
      open();
      return;
    }
    hits.forEach((h, idx) => {
      const row = document.createElement('div');
      row.className = 'fund-search-row';
      row.dataset.idx = String(idx);

      const top = document.createElement('div');
      top.className = 'fund-search-row-top';
      const name = document.createElement('span');
      name.className = 'fund-search-name';
      name.textContent = h.nombre || '';
      const isin = document.createElement('span');
      isin.className = 'fund-search-isin mono';
      isin.textContent = h.isin;
      top.appendChild(name);
      top.appendChild(isin);

      const bot = document.createElement('div');
      bot.className = 'fund-search-row-bot';
      const meta = document.createElement('span');
      meta.textContent = [h.gestora, h.tipo].filter(Boolean).join(' · ');
      bot.appendChild(meta);
      if (h.has_brochure) {
        const badge = document.createElement('span');
        badge.className = 'badge badge-brochure';
        badge.textContent = 'Folleto CNMV';
        bot.appendChild(badge);
      }

      row.appendChild(top);
      row.appendChild(bot);
      row.addEventListener('mousedown', (e) => {
        e.preventDefault();
        choose(idx);
      });
      dropdownEl.appendChild(row);
    });
    open();
  };

  const choose = (idx) => {
    const hit = currentHits[idx];
    if (!hit) return;
    inputEl.value = `${hit.isin} · ${hit.nombre}`;
    close();
    onSelect(hit);
  };

  const doSearch = async (q) => {
    if (q === lastQuery) return;
    lastQuery = q;
    const filters = getFilters ? getFilters() : {};
    try {
      const hits = await api.fundSearch({
        q: q || undefined,
        tipo: filters.tipo || undefined,
        gestora: filters.gestora || undefined,
        onlyWithBrochure: !!filters.onlyWithBrochure,
        limit: 20,
      });
      currentHits = hits;
      render(hits);
    } catch (e) {
      dropdownEl.innerHTML = `<div class="fund-search-empty" style="color: var(--loss-700)">Error: ${e.message}</div>`;
      open();
    }
  };

  inputEl.setAttribute('autocomplete', 'off');
  inputEl.setAttribute('aria-label', `Buscador fondo ${label || ''}`);
  inputEl.addEventListener('focus', () => {
    if (currentHits.length === 0) {
      doSearch('');
    } else {
      open();
    }
  });
  inputEl.addEventListener('blur', () => {
    setTimeout(close, 150); // dejar tiempo al mousedown
  });
  inputEl.addEventListener('input', () => {
    const q = inputEl.value.trim();
    clearTimeout(timer);
    if (q.length < MIN_CHARS) {
      currentHits = [];
      close();
      return;
    }
    timer = setTimeout(() => doSearch(q), DEBOUNCE_MS);
  });
  inputEl.addEventListener('keydown', (e) => {
    if (dropdownEl.classList.contains('hidden')) return;
    const rows = dropdownEl.querySelectorAll('.fund-search-row');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      active = Math.min(active + 1, rows.length - 1);
      updateActive(rows);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      active = Math.max(active - 1, 0);
      updateActive(rows);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (active >= 0) choose(active);
    } else if (e.key === 'Escape') {
      close();
    }
  });

  const updateActive = (rows) => {
    rows.forEach((r, idx) => {
      r.classList.toggle('active', idx === active);
    });
    if (active >= 0 && rows[active]) {
      rows[active].scrollIntoView({ block: 'nearest' });
    }
  };

  return {
    refresh: () => {
      lastQuery = null;
      doSearch(inputEl.value.trim());
    },
    clear: () => {
      inputEl.value = '';
      currentHits = [];
      close();
    },
    setValue: (hit) => {
      inputEl.value = `${hit.isin} · ${hit.nombre}`;
    },
  };
}
