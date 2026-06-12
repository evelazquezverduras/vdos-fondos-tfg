// store.js — Estado compartido en sessionStorage (gestor, ultima recomendacion).

const KEY_GESTOR = 'vdos.gestor_banco';

export const store = {
  getGestor() {
    try { return sessionStorage.getItem(KEY_GESTOR) || ''; }
    catch { return ''; }
  },
  setGestor(value) {
    try { sessionStorage.setItem(KEY_GESTOR, value || ''); }
    catch { /* no-op */ }
  },
};
