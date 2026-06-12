# Datos de muestra (ficticios)

Todos los datos de esta carpeta son **inventados** y no guardan relación con
ningún fondo, gestora ni cliente real. Sirven para que el código se ejecute y
se entienda sin exponer información de VDOS.

- `pdfs_extracted.json` / `pdfs_extracted_codes.json`: 3 fondos de ejemplo en
  el esquema canónico de 55 campos (salida del extractor). La versión `_codes`
  usa códigos neutros en P00/P05/P06.
- `csv/meta_muestra.csv` y `csv/vl_historico_muestra.csv`: metadata y serie de
  valor liquidativo de los 3 fondos, entrada de `web/backend/scripts/build_db.py`
  para generar `web/data/funds.sqlite` (el comparador).
- `folletos/`: vacía; aquí irían folletos PDF públicos de la CNMV.
