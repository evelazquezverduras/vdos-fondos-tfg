// news-card.js — Card de noticia (sentimiento positivo asumido, no se muestra).
//
// La seccion de Noticias del Asesor filtra ya por positivas, por lo que
// no se pinta el badge "+1.00 positivo": seria redundante. Si en el
// futuro se mezclan sentimientos, restaurar badgeFor().

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export function newsCard(item) {
  const card = el('div', 'news-card');

  const title = el('div', 'news-title');
  if (item.link) {
    const a = el('a');
    a.href = item.link;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = item.title || '(sin título)';
    title.appendChild(a);
  } else {
    title.textContent = item.title || '(sin título)';
  }
  card.appendChild(title);

  const meta = el('div', 'news-meta');
  if (item.source) meta.appendChild(el('span', '', item.source));
  if (item.published) {
    if (item.source) meta.appendChild(el('span', '', '·'));
    meta.appendChild(el('span', '', item.published));
  }
  card.appendChild(meta);

  if (item.summary) {
    const s = item.summary.length > 220 ? item.summary.slice(0, 217) + '…' : item.summary;
    card.appendChild(el('div', 'news-summary', s));
  }

  return card;
}
