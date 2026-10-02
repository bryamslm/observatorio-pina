# Calidad de datos — hallazgos

1. **CRS mal declarado en el WFS de MOCUPP.** El GeoJSON dice EPSG:4326 (o 4979) pero las
   coordenadas son CRTM05 (EPSG:5367), p. ej. `487784, 1158470`. Sin corregirlo el área da 0 ha.
   Se fuerza 5367 en `procesar.py`.
2. **Capa `Pina_2016` incompleta.** 298 polígonos y 5.958,79 ha, contra 68.643,33 ha publicadas
   para 2016. Se excluye de `fact_area_pina`; la capa de cambio 2015–2016 sí se conserva.
3. **`CÓDIGO` del límite distrital no es único.** Chomes (Puntarenas) y San Juan (Abangares)
   comparten 160105. La llave correcta es `CÓDIGO_DTA` (provincia-cantón-distrito); hay un
   `assert` que lo garantiza.
4. **Rótulos de cambio distintos por entrega** ("Pérdida", "Pérdida de CA", "Sin cambi",
   "Sin cambios en paisaje productivo"). Se normalizan a `perdida_cobertura_arborea`,
   `sin_cambio`, `otros_cambios`.
5. **Comtrade 2025** sin datos para Costa Rica todavía (0 filas); el mundo trae 89 reportantes
   parciales. No se usa 2025 en comparaciones anuales.
6. **Peso de 2024 en Comtrade no es creíble.** Costa Rica reporta 4.047 mil t exportadas en 2024
   contra 2.114 mil t en 2023, con un valor que solo sube 16 % (USD 1.176 M → 1.363 M). El precio
   implícito cae de 0,556 a 0,337 USD/kg. Es casi el doble de volumen sin respaldo en producción
   (FAOSTAT 2024: 3,12 M t), así que se trata como error de registro: el kg de 2024 se marca y no
   se usa para USD/kg. Pendiente contrastar con el portal de PROCOMER.
