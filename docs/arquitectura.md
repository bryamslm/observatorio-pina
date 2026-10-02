# Arquitectura — Observatorio de la piña CR

Objetivo: un tablero BI construido con el mismo stack que usa una empresa piñera
costarricense (Power BI + SQL + ERP Business Central + Panal 360 + nube Azure/AWS),
alimentado con datos públicos reales del sector.

## Capas

```
FUENTES                    INGESTA              ALMACÉN (SQL)             SEMÁNTICO          CONSUMO
─────────────────────────  ───────────────────  ────────────────────────  ─────────────────  ──────────────────────
MOCUPP Piña (WFS, CENAT)   scripts/descargar.py stg.*  (crudo tipado)     Power BI           Power BI (.pbix)
IGN límites (WFS, SNIT)    idempotente, sin  →  dw.dim_* / dw.fact_*  →   modelo estrella →  bryamlopez.com/datos
UN Comtrade HS 080430      clave                vistas T-SQL de KPI       medidas DAX        (capturas + mapa)
FAOSTAT QCL                scripts/procesar.py                            RLS por finca
[Operación simulada]       (reproyección,
 estructura BC + Panal 360  cruce espacial)
```

**Almacén: SQL Server (T-SQL).** Business Central corre sobre SQL Server/Azure SQL,
Power BI tiene su mejor conector ahí y el salto a Azure SQL es directo. Local con
SQL Server Developer/Express; opcional: Azure SQL para demostrar despliegue en nube.

## Modelo estrella

| Tabla | Grano | Fuente |
|---|---|---|
| `dim_anio` | año | — |
| `dim_distrito` | distrito (código DTA) | IGN |
| `dim_pais` | país (M49) | Comtrade |
| `fact_area_pina` | año × distrito | MOCUPP |
| `fact_cambio_cobertura` | periodo × distrito × transición | MOCUPP |
| `fact_export_cr` | año × país destino | Comtrade |
| `fact_export_mundo` | año × país exportador | Comtrade |
| `fact_produccion` | año × país | FAOSTAT |
| *(simulado)* `fact_cosecha`, `fact_labores`, `fact_ventas` | día × bloque / embarque | estructura Panal 360 / Business Central |

## Páginas del reporte y sus KPI

1. **Mercado** — USD exportados, kg, precio implícito USD/kg, concentración por destino, cuota de CR en el mundo.
2. **Territorio** — ha de piña por región/cantón/distrito, crecimiento, foco Huetar Norte y Pocosol.
3. **Sostenibilidad** — ha de pérdida de cobertura arbórea asociada a piña por periodo y distrito; % del área sin cambio.
4. **Productividad** — rendimiento t/ha de CR vs principales productores (FAO).
5. **Operación** *(datos simulados, rotulados como tales)* — cajas/ha, % fruta exportable vs rechazo, distribución de calibres, costo por caja y por ha, labores por bloque, presupuesto vs real.

## Validación de las cifras (ver calidad-de-datos.md)

| Control | Calculado | Publicado |
|---|---|---|
| Área piña 2015 | 58.427,22 ha | 58.426,11 ha (mocupp.org) |
| Área piña 2018 | 65.670,69 ha | 65.671 ha (mocupp.org) |
| Pérdida CA 2017–2018 | 343 ha | "más de 343 ha" (MOCUPP 2019) |
| Área piña 2016 | 5.958,79 ha | 68.643,33 ha → **capa incompleta, excluida** |
