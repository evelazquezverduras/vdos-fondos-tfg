"""build_db.py -- Conversion one-shot CSV --> SQLite para el Comparador.

Convierte los dos CSVs de VDOS (metadata de fondos + historico de VL) a una
base SQLite con indices, para que la API consulte en <50ms sin cargar 178 MB
en RAM.

Uso (desde tfg/web/):

    python backend/scripts/build_db.py

Si los CSV viven en otra ruta, ajustar las constantes META_CSV / HIST_CSV.
La salida queda en tfg/web/data/funds.sqlite.

El script es idempotente: si la BD existe, la rehace desde cero.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
import time
from pathlib import Path


# tfg/web/backend/scripts/build_db.py -> tfg/
_WEB_DIR = Path(__file__).resolve().parents[2]
_TFG_DIR = _WEB_DIR.parent

META_CSV = _TFG_DIR / "_SELECT_f_isin_f_nfondo_AS_nombre_f_nombreg_AS_gestora_f_nombred_202605211059.csv"
HIST_CSV = _TFG_DIR / "_SELECT_v_isin_v_tiempo_AS_fecha_v_vliq_AS_vl_v_patrim_AS_patrim_202605211102.csv"

DB_PATH = _WEB_DIR / "data" / "funds.sqlite"


# Columnas del CSV de metadata, tipadas. Cubre las 54 columnas del SELECT.
META_COLUMNS: list[tuple[str, str]] = [
    ("isin", "TEXT PRIMARY KEY"),
    ("nombre", "TEXT"),
    ("gestora", "TEXT"),
    ("depositaria", "TEXT"),
    ("tipo", "TEXT"),
    ("cat_macro", "TEXT"),
    ("cat_vdos", "TEXT"),
    ("fecha_registro", "TEXT"),
    ("aportacion_minima", "REAL"),
    ("divisa_apmin", "TEXT"),
    ("divisa", "TEXT"),
    ("vl", "REAL"),
    ("patrimonio_miles", "REAL"),
    ("participaciones", "REAL"),
    ("fecha_snapshot", "TEXT"),
    ("com_gestion", "REAL"),
    ("com_depositario", "REAL"),
    ("com_reembolso", "REAL"),
    ("com_total", "REAL"),
    ("retrocesion", "REAL"),
    ("r1d", "REAL"), ("r1s", "REAL"), ("r1m", "REAL"), ("r3m", "REAL"),
    ("r6m", "REAL"), ("r1a", "REAL"), ("r2a", "REAL"), ("r3a", "REAL"),
    ("r5a", "REAL"), ("rinicio", "REAL"),
    ("ra", "REAL"), ("ra1", "REAL"), ("ra2", "REAL"), ("ra3", "REAL"),
    ("ra4", "REAL"), ("ra5", "REAL"), ("ra6", "REAL"),
    ("ytd1", "REAL"), ("ytd3", "REAL"), ("ytd5", "REAL"),
    ("volatilidad", "REAL"), ("sharpe", "REAL"), ("ratio_info", "REAL"),
    ("tracking_error", "REAL"), ("alfa", "REAL"), ("beta", "REAL"),
    ("r_cuadrado", "REAL"),
    ("qr1m", "TEXT"), ("qr3m", "TEXT"), ("qr1a", "TEXT"),
    ("qr3a", "TEXT"), ("qr5a", "TEXT"),
    ("prr1a", "TEXT"), ("prr3a", "TEXT"), ("prr5a", "TEXT"),
]
META_REAL_COLS = {name for name, t in META_COLUMNS if t == "REAL"}


def _parse_real(s: str) -> float | None:
    """Convierte string vacio a None, lo demas a float. Tolera coma decimal."""
    if s is None or s == "":
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _build_schema(conn: sqlite3.Connection) -> None:
    cols_sql = ",\n  ".join(f'"{name}" {typ}' for name, typ in META_COLUMNS)
    conn.execute(f"DROP TABLE IF EXISTS fund_meta;")
    conn.execute(f"CREATE TABLE fund_meta (\n  {cols_sql}\n);")

    conn.execute("DROP TABLE IF EXISTS vl_history;")
    conn.execute(
        """
        CREATE TABLE vl_history (
          isin TEXT NOT NULL,
          fecha TEXT NOT NULL,
          vl REAL NOT NULL,
          patrimonio REAL,
          PRIMARY KEY (isin, fecha)
        ) WITHOUT ROWID;
        """
    )


def _load_meta(conn: sqlite3.Connection) -> int:
    if not META_CSV.exists():
        raise FileNotFoundError(f"No encuentro {META_CSV}")
    col_names = [c[0] for c in META_COLUMNS]
    placeholders = ", ".join("?" * len(col_names))
    cols_quoted = ", ".join(f'"{c}"' for c in col_names)
    insert_sql = f"INSERT INTO fund_meta ({cols_quoted}) VALUES ({placeholders})"

    inserted = 0
    with open(META_CSV, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        # Validacion ligera: las cabeceras del CSV deben contener todas las nuestras
        missing = [c for c in col_names if c not in reader.fieldnames]
        if missing:
            raise RuntimeError(
                f"El CSV de metadata no tiene estas columnas esperadas: {missing}"
            )
        batch: list[tuple] = []
        for row in reader:
            tup = []
            for c in col_names:
                v = row.get(c, "")
                if c in META_REAL_COLS:
                    tup.append(_parse_real(v))
                else:
                    tup.append(v if v != "" else None)
            batch.append(tuple(tup))
            if len(batch) >= 1000:
                conn.executemany(insert_sql, batch)
                inserted += len(batch)
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
            inserted += len(batch)
    return inserted


def _load_history(conn: sqlite3.Connection) -> int:
    if not HIST_CSV.exists():
        raise FileNotFoundError(f"No encuentro {HIST_CSV}")
    insert_sql = "INSERT OR IGNORE INTO vl_history (isin, fecha, vl, patrimonio) VALUES (?, ?, ?, ?)"
    inserted = 0
    skipped = 0
    with open(HIST_CSV, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        batch: list[tuple] = []
        t0 = time.time()
        for row in reader:
            isin = row.get("isin", "")
            fecha = row.get("fecha", "")
            vl = _parse_real(row.get("vl", ""))
            patrim = _parse_real(row.get("patrimonio", ""))
            if not isin or not fecha or vl is None:
                skipped += 1
                continue
            batch.append((isin, fecha, vl, patrim))
            if len(batch) >= 50000:
                conn.executemany(insert_sql, batch)
                inserted += len(batch)
                batch.clear()
                print(
                    f"  ...{inserted:,} filas insertadas "
                    f"({inserted/(time.time()-t0):.0f}/s)"
                )
        if batch:
            conn.executemany(insert_sql, batch)
            inserted += len(batch)
    if skipped:
        print(f"  (saltadas {skipped} filas sin isin/fecha/vl)")
    return inserted


def _build_indices(conn: sqlite3.Connection) -> None:
    """Indices secundarios para las consultas del comparador."""
    # PRIMARY KEY (isin, fecha) ya cubre lookup por isin y rangos de fecha.
    # Añadimos un indice por gestora para acelerar /api/funds/search.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_gestora ON fund_meta(gestora);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_tipo ON fund_meta(tipo);")
    # Indice FTS-lite: no usamos FTS5 para no añadir dependencias; el LIKE
    # con prefijo busca bien sobre nombre/isin si los hacemos UPPER.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_nombre ON fund_meta(nombre);")


def main() -> None:
    if not META_CSV.exists():
        print(f"ERROR: no encuentro {META_CSV}", file=sys.stderr)
        sys.exit(2)
    if not HIST_CSV.exists():
        print(f"ERROR: no encuentro {HIST_CSV}", file=sys.stderr)
        sys.exit(2)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        print(f"Borrando BD existente: {DB_PATH}")
        DB_PATH.unlink()

    print(f"Creando BD en: {DB_PATH}")
    t0 = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        # Pragmas para acelerar la insercion masiva.
        conn.execute("PRAGMA journal_mode = OFF;")
        conn.execute("PRAGMA synchronous = OFF;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA cache_size = -200000;")  # 200 MB

        print("1/4 Creando esquema...")
        _build_schema(conn)

        print(f"2/4 Cargando metadata desde {META_CSV.name}...")
        n_meta = _load_meta(conn)
        print(f"     -> {n_meta:,} fondos en fund_meta")

        print(f"3/4 Cargando historico VL desde {HIST_CSV.name}...")
        n_hist = _load_history(conn)
        print(f"     -> {n_hist:,} filas en vl_history")

        print("4/4 Creando indices secundarios...")
        _build_indices(conn)

        conn.commit()
        print("Optimizando (VACUUM + ANALYZE)...")
        conn.execute("ANALYZE;")
        conn.commit()
    finally:
        conn.close()

    # VACUUM fuera de la transaccion principal
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("VACUUM;")
    finally:
        conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    elapsed = time.time() - t0
    print(f"\nOK. {DB_PATH.name} = {size_mb:.1f} MB. Tiempo total: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
