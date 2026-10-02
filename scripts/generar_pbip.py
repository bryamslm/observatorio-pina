"""
Genera el reporte de Power BI como codigo: un proyecto PBIP (modelo semantico en
TMDL + reporte en PBIR) en powerbi/. Power BI Desktop lo abre directamente
(Archivo > Abrir > powerbi/Observatorio.pbip) y desde ahi se puede guardar como .pbix.

    python scripts/generar_pbip.py

Por que como codigo: el modelo, las medidas DAX y cada visual quedan versionados en
git y se pueden revisar en un diff, igual que el resto del pipeline.
"""
import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "powerbi"
NAME = "Observatorio"
NS = uuid.UUID("6f1c0a52-3c1e-4b8e-9a7e-2f4e8b1d9c10")


def tag(*parts: str) -> str:
    """lineageTag estable: mismo nombre -> mismo GUID en cada corrida."""
    return str(uuid.uuid5(NS, "/".join(parts)))


def q(name: str) -> str:
    """Nombre TMDL/DAX: se cita si tiene espacios o caracteres no ASCII."""
    return name if name.isidentifier() and name.isascii() else "'" + name.replace("'", "''") + "'"


# --------------------------------------------------------------------------------------
# Modelo: tabla en Power BI -> (esquema, tabla SQL, columnas [(nombre, tipo, formato, oculta)])
# --------------------------------------------------------------------------------------
I, D, S, T, B = "int64", "double", "string", "dateTime", "boolean"
TABLES = {
    "Año": ("dw", "dim_anio", [("anio", I, "0", False)]),
    "Distrito": ("dw", "dim_distrito", [
        ("cod_distrito", I, "0", True), ("provincia", S, None, False), ("canton", S, None, False),
        ("distrito", S, None, False), ("cod_canton", I, "0", True), ("cod_provincia", I, "0", True),
        ("region", S, None, False), ("area_distrito_ha", D, "#,0", True)]),
    "País": ("dw", "dim_pais", [
        ("cod_pais", I, "0", True), ("pais", S, None, False), ("iso3", S, None, False),
        ("es_agregado", B, None, True)]),
    "Área piña": ("dw", "fact_area_pina", [
        ("anio", I, "0", True), ("cod_distrito", I, "0", True), ("ha", D, "#,0", True)]),
    "Cambio cobertura": ("dw", "fact_cambio_cobertura", [
        ("periodo", S, None, False), ("anio_desde", I, "0", True), ("anio_hasta", I, "0", True),
        ("cod_distrito", I, "0", True), ("cober_desde", S, None, False), ("cober_hasta", S, None, False),
        ("tipo_cambio", S, None, False), ("ha", D, "#,0", True)]),
    "Exportaciones CR": ("dw", "fact_export_cr", [
        ("anio", I, "0", True), ("cod_pais", I, "0", True), ("usd", D, "#,0", True), ("kg", D, "#,0", True)]),
    "Exportaciones mundo": ("dw", "fact_export_mundo", [
        ("anio", I, "0", True), ("cod_pais", I, "0", True), ("usd", D, "#,0", True), ("kg", D, "#,0", True)]),
    "Producción FAO": ("dw", "fact_produccion", [
        ("anio", I, "0", True), ("cod_pais", I, "0", True), ("area_cosechada_ha", D, "#,0", True),
        ("produccion_t", D, "#,0", True), ("rendimiento_kg_ha", D, "#,0", True)]),
    "Fecha": ("ops", "dim_fecha", [
        ("fecha", T, "dd/mm/yyyy", False), ("anio", I, "0", False), ("mes", I, "0", False),
        ("semana", I, "0", False)]),
    "Bloque": ("ops", "dim_bloque", [
        ("cod_bloque", S, None, False), ("finca", S, None, False), ("ha", D, "#,0.00", False),
        ("fecha_siembra", T, "dd/mm/yyyy", False), ("variedad", S, None, False)]),
    "Ciclo": ("ops", "dim_ciclo", [
        ("ciclo_id", S, None, False), ("cod_bloque", S, None, True), ("fecha_siembra", T, "dd/mm/yyyy", False),
        ("inicio_cosecha", T, "dd/mm/yyyy", False), ("completo", B, None, False)]),
    "Cosecha": ("ops", "fact_cosecha", [
        ("fecha", T, "dd/mm/yyyy", True), ("cod_bloque", S, None, True), ("ciclo_id", S, None, True),
        ("calibre", I, "0", False), ("cajas_exportables", I, "#,0", True), ("cajas_rechazo", I, "#,0", True)]),
    "Labores": ("ops", "fact_labores", [
        ("fecha", T, "dd/mm/yyyy", True), ("cod_bloque", S, None, True), ("ciclo_id", S, None, True),
        ("labor", S, None, False), ("jornales", D, "#,0.0", True), ("costo_real_crc", D, "#,0", True),
        ("costo_presupuesto_crc", D, "#,0", True)]),
    "Ventas": ("ops", "fact_ventas", [
        ("fecha", T, "dd/mm/yyyy", True), ("cliente", S, None, False), ("cod_bloque", S, None, True),
        ("calibre", I, "0", False), ("cajas", I, "#,0", True), ("usd", D, "#,0", True)]),
}

# (desde tabla.columna, hacia tabla.columna) — muchos a uno, filtro de la dimension al hecho.
RELATIONSHIPS = [
    ("Área piña", "anio", "Año", "anio"), ("Área piña", "cod_distrito", "Distrito", "cod_distrito"),
    ("Cambio cobertura", "cod_distrito", "Distrito", "cod_distrito"),
    ("Cambio cobertura", "anio_hasta", "Año", "anio"),
    ("Exportaciones CR", "anio", "Año", "anio"), ("Exportaciones CR", "cod_pais", "País", "cod_pais"),
    ("Exportaciones mundo", "anio", "Año", "anio"), ("Exportaciones mundo", "cod_pais", "País", "cod_pais"),
    ("Producción FAO", "anio", "Año", "anio"), ("Producción FAO", "cod_pais", "País", "cod_pais"),
    ("Cosecha", "fecha", "Fecha", "fecha"), ("Cosecha", "cod_bloque", "Bloque", "cod_bloque"),
    ("Cosecha", "ciclo_id", "Ciclo", "ciclo_id"),
    ("Labores", "fecha", "Fecha", "fecha"), ("Labores", "cod_bloque", "Bloque", "cod_bloque"),
    ("Labores", "ciclo_id", "Ciclo", "ciclo_id"),
    ("Ventas", "fecha", "Fecha", "fecha"), ("Ventas", "cod_bloque", "Bloque", "cod_bloque"),
    # Ciclo -> Bloque NO se relaciona: Cosecha ya llega a Bloque directo y una segunda ruta
    # haria el modelo ambiguo. El ha de un ciclo se busca con LOOKUPVALUE.
]

# --------------------------------------------------------------------------------------
# Medidas DAX: (carpeta, nombre, expresion, formato, descripcion)
# --------------------------------------------------------------------------------------
NO_2024 = "KEEPFILTERS('Año'[anio] <> 2024)"   # volumen 2024 de Comtrade no es creible
HASTA_2024 = "KEEPFILTERS('Año'[anio] <= 2024)"  # 2025 aun no tiene todos los reportantes
MEASURES = [
    # Mercado ---------------------------------------------------------------------------
    ("Mercado", "Exportaciones USD", "SUM('Exportaciones CR'[usd])", "$#,0",
     "Valor FOB exportado por Costa Rica (HS 080430), UN Comtrade."),
    ("Mercado", "Exportaciones USD (último año)",
     "VAR y = CALCULATE(MAX('Exportaciones CR'[anio]), REMOVEFILTERS('País'))\n"
     "RETURN CALCULATE([Exportaciones USD], 'Exportaciones CR'[anio] = y)", "$#,0",
     "Exportaciones del año más reciente dentro del filtro."),
    ("Mercado", "Exportaciones t",
     f"CALCULATE(DIVIDE(SUM('Exportaciones CR'[kg]), 1000), {NO_2024})", "#,0",
     "Toneladas exportadas. Excluye 2024: Comtrade reporta casi el doble del volumen de 2023."),
    ("Mercado", "Precio USD/kg",
     f"CALCULATE(DIVIDE(SUM('Exportaciones CR'[usd]), SUM('Exportaciones CR'[kg])), {NO_2024})", "$0.000",
     "Precio implícito FOB. Excluye 2024 por la anomalía de volumen."),
    ("Mercado", "Precio USD por caja de 12 kg", "[Precio USD/kg] * 12", "$0.00",
     "Precio implícito llevado a la caja estándar de exportación."),
    ("Mercado", "Var % exportaciones a/a",
     "VAR y = CALCULATE(MAX('Exportaciones CR'[anio]), REMOVEFILTERS('País'))\n"
     "VAR actual = CALCULATE([Exportaciones USD], 'Año'[anio] = y)\n"
     "VAR prev = CALCULATE([Exportaciones USD], 'Año'[anio] = y - 1)\n"
     "RETURN DIVIDE(actual - prev, prev)", "0.0%",
     "Último año con datos contra el anterior (no suma años)."),
    ("Mercado", "Cuota del destino %",
     "DIVIDE([Exportaciones USD], CALCULATE([Exportaciones USD], REMOVEFILTERS('País')))", "0.0%",
     "Peso de cada país de destino en el total exportado."),
    ("Mercado", "Exportaciones mundo USD",
     f"CALCULATE(SUM('Exportaciones mundo'[usd]), 'País'[es_agregado] = FALSE(), {HASTA_2024})", "$#,0",
     "Exportaciones de cada país al mundo (sin agregados regionales)."),
    ("Mercado", "Cuota mundial CR %",
     "DIVIDE(CALCULATE([Exportaciones mundo USD], 'País'[cod_pais] = 188),\n"
     "       CALCULATE([Exportaciones mundo USD], REMOVEFILTERS('País')))", "0.0%",
     "Participación de Costa Rica en las exportaciones mundiales de piña."),
    # Territorio ------------------------------------------------------------------------
    ("Territorio", "Hectáreas de piña",
     "VAR y = CALCULATE(MAX('Área piña'[anio]), REMOVEFILTERS('Distrito'))\n"
     "RETURN CALCULATE(SUM('Área piña'[ha]), 'Área piña'[anio] = y)", "#,0",
     "Área de piña de la medición más reciente dentro del filtro (MOCUPP). No suma años."),
    ("Territorio", "Participación Huetar Norte %",
     "DIVIDE(CALCULATE([Hectáreas de piña], 'Distrito'[region] = \"Huetar Norte\"),\n"
     "       CALCULATE([Hectáreas de piña], REMOVEFILTERS('Distrito')))", "0.0%",
     "Peso de la región Huetar Norte en el área nacional de piña."),
    ("Territorio", "Crecimiento ha 2000-2019",
     "CALCULATE(SUM('Área piña'[ha]), 'Área piña'[anio] = 2019)\n"
     "  - CALCULATE(SUM('Área piña'[ha]), 'Área piña'[anio] = 2000)", "#,0",
     "Hectáreas ganadas entre la primera y la última medición de MOCUPP."),
    ("Territorio", "% del distrito sembrado",
     "DIVIDE([Hectáreas de piña], SUM('Distrito'[area_distrito_ha]))", "0.0%",
     "Proporción del territorio del distrito cubierta por piña."),
    # Sostenibilidad --------------------------------------------------------------------
    ("Sostenibilidad", "Ha pérdida de bosque",
     "CALCULATE(SUM('Cambio cobertura'[ha]), 'Cambio cobertura'[tipo_cambio] = \"perdida_cobertura_arborea\")",
     "#,0", "Cobertura arbórea convertida a piña en el periodo (MOCUPP)."),
    ("Sostenibilidad", "Ha sin cambio",
     "CALCULATE(SUM('Cambio cobertura'[ha]), 'Cambio cobertura'[tipo_cambio] = \"sin_cambio\")", "#,0",
     "Piña sobre terreno que ya era productivo: sin pérdida de bosque."),
    ("Sostenibilidad", "Pérdida último periodo (ha)",
     "VAR y = CALCULATE(MAX('Cambio cobertura'[anio_hasta]), REMOVEFILTERS('Distrito'))\n"
     "RETURN CALCULATE([Ha pérdida de bosque], 'Cambio cobertura'[anio_hasta] = y)", "#,0",
     "Pérdida de bosque del periodo más reciente dentro del filtro."),
    ("Sostenibilidad", "% del área con pérdida",
     "DIVIDE([Ha pérdida de bosque], SUM('Cambio cobertura'[ha]))", "0.00%",
     "Proporción del área analizada donde hubo pérdida de bosque."),
    # Productividad ---------------------------------------------------------------------
    ("Productividad", "Producción t",
     "CALCULATE(SUM('Producción FAO'[produccion_t]), 'País'[es_agregado] = FALSE())", "#,0",
     "Producción de piña (FAOSTAT), solo países."),
    ("Productividad", "Área cosechada ha",
     "CALCULATE(SUM('Producción FAO'[area_cosechada_ha]), 'País'[es_agregado] = FALSE())", "#,0",
     "Área cosechada (FAOSTAT), solo países."),
    ("Productividad", "Rendimiento t/ha", "DIVIDE([Producción t], [Área cosechada ha])", "#,0.0",
     "Toneladas por hectárea cosechada."),
    ("Productividad", "Rendimiento CR t/ha",
     "CALCULATE([Rendimiento t/ha], 'País'[cod_pais] = 188)", "#,0.0", "Rendimiento de Costa Rica."),
    ("Productividad", "Rendimiento mundial t/ha",
     "CALCULATE([Rendimiento t/ha], REMOVEFILTERS('País'))", "#,0.0",
     "Rendimiento promedio ponderado de todos los productores."),
    ("Productividad", "Rendimiento CR t/ha (último año)",
     "VAR y = CALCULATE(MAX('Producción FAO'[anio]), REMOVEFILTERS('País'))\n"
     "RETURN CALCULATE([Rendimiento CR t/ha], 'Producción FAO'[anio] = y)", "#,0.0",
     "Rendimiento de Costa Rica en el último año disponible."),
    ("Productividad", "Rendimiento mundial t/ha (último año)",
     "VAR y = CALCULATE(MAX('Producción FAO'[anio]), REMOVEFILTERS('País'))\n"
     "RETURN CALCULATE([Rendimiento mundial t/ha], 'Producción FAO'[anio] = y)", "#,0.0",
     "Rendimiento mundial en el último año disponible."),
    ("Productividad", "Producción t (último año)",
     "VAR y = CALCULATE(MAX('Producción FAO'[anio]), REMOVEFILTERS('País'))\n"
     "RETURN CALCULATE([Producción t], 'Producción FAO'[anio] = y)", "#,0",
     "Producción del año más reciente disponible en FAOSTAT."),
    ("Productividad", "Producción CR t (último año)",
     "CALCULATE([Producción t (último año)], 'País'[cod_pais] = 188)", "#,0",
     "Producción de Costa Rica en el último año disponible."),
    # Operacion (SIMULADA) --------------------------------------------------------------
    ("Operación (simulada)", "Cajas exportables", "SUM('Cosecha'[cajas_exportables])", "#,0",
     "DATOS SIMULADOS. Cajas de 12 kg aptas para exportación."),
    ("Operación (simulada)", "Cajas totales",
     "SUM('Cosecha'[cajas_exportables]) + SUM('Cosecha'[cajas_rechazo])", "#,0",
     "DATOS SIMULADOS. Exportables más rechazo."),
    ("Operación (simulada)", "% exportable", "DIVIDE([Cajas exportables], [Cajas totales])", "0.0%",
     "DATOS SIMULADOS. Aprovechamiento de la fruta cosechada."),
    ("Operación (simulada)", "Cajas por ha por ciclo",
     "AVERAGEX(\n"
     "    FILTER('Ciclo', 'Ciclo'[completo]),\n"
     "    DIVIDE(CALCULATE([Cajas totales]),\n"
     "           LOOKUPVALUE('Bloque'[ha], 'Bloque'[cod_bloque], 'Ciclo'[cod_bloque])))", "#,0",
     "DATOS SIMULADOS. Productividad promedio de los ciclos completos."),
    ("Operación (simulada)", "Costo real CRC", "SUM('Labores'[costo_real_crc])", "₡#,0",
     "DATOS SIMULADOS. Costo de campo registrado por labor."),
    ("Operación (simulada)", "Costo presupuesto CRC", "SUM('Labores'[costo_presupuesto_crc])", "₡#,0",
     "DATOS SIMULADOS. Costo de campo presupuestado."),
    ("Operación (simulada)", "Desviación vs presupuesto %",
     "DIVIDE([Costo real CRC] - [Costo presupuesto CRC], [Costo presupuesto CRC])", "0.0%",
     "DATOS SIMULADOS. Positivo = sobrecosto."),
    ("Operación (simulada)", "Costo por caja exportable CRC",
     "DIVIDE(CALCULATE([Costo real CRC], 'Ciclo'[completo] = TRUE()),\n"
     "       CALCULATE([Cajas exportables], 'Ciclo'[completo] = TRUE()))", "₡#,0",
     "DATOS SIMULADOS. Costo de campo por caja, solo ciclos completos (sin empaque ni flete)."),
    ("Operación (simulada)", "Ventas USD", "SUM('Ventas'[usd])", "$#,0", "DATOS SIMULADOS."),
    ("Operación (simulada)", "Precio promedio USD/caja", "DIVIDE([Ventas USD], SUM('Ventas'[cajas]))",
     "$0.00", "DATOS SIMULADOS. Calibrado con el precio implícito real de Comtrade 2023."),
    ("Operación (simulada)", "Tipo de cambio CRC/USD", "505", "0", "Supuesto fijo de la simulación."),
    ("Operación (simulada)", "Margen de campo USD/caja",
     "[Precio promedio USD/caja] - DIVIDE([Costo por caja exportable CRC], [Tipo de cambio CRC/USD])",
     "$0.00", "DATOS SIMULADOS. Precio menos costo de campo; no incluye empaque, flete ni indirectos."),
]


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def semantic_model():
    sm = OUT / f"{NAME}.SemanticModel"
    write(sm / "definition.pbism", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {"qnaEnabled": False}}, indent=2))
    d = sm / "definition"
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1601\n")
    refs = "\n".join(f"ref table {q(t)}" for t in [*TABLES, "Medidas"])
    write(d / "model.tmdl",
          "model Model\n\tculture: es-ES\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
          "\tdiscourageImplicitMeasures\n\tsourceQueryCulture: es-ES\n\tdataAccessOptions\n"
          "\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
          f"annotation PBI_QueryOrder = {json.dumps(['Servidor', 'BaseDatos', *TABLES], ensure_ascii=False)}\n\n"
          f"{refs}\n")
    write(d / "expressions.tmdl",
          "/// Servidor SQL Server. Por defecto, el tunel SSH local hacia el servidor del proyecto.\n"
          "expression Servidor = \"127.0.0.1,14333\" meta [IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]\n"
          f"\tlineageTag: {tag('expr', 'Servidor')}\n\n\tannotation PBI_ResultType = Text\n\n"
          "expression BaseDatos = \"observatorio_pina\" meta [IsParameterQuery=true, Type=\"Text\", IsParameterQueryRequired=true]\n"
          f"\tlineageTag: {tag('expr', 'BaseDatos')}\n\n\tannotation PBI_ResultType = Text\n")

    for table, (schema, sql_table, cols) in TABLES.items():
        lines = [f"table {q(table)}", f"\tlineageTag: {tag('t', table)}", ""]
        for name, dtype, fmt, hidden in cols:
            lines.append(f"\tcolumn {q(name)}")
            lines.append(f"\t\tdataType: {dtype}")
            if hidden:
                lines.append("\t\tisHidden")
            if fmt:
                lines.append(f"\t\tformatString: {fmt}")
            lines.append(f"\t\tlineageTag: {tag('c', table, name)}")
            lines.append("\t\tsummarizeBy: none")
            lines.append(f"\t\tsourceColumn: {name}")
            lines.append("")
            lines.append("\t\tannotation SummarizationSetBy = Automatic")
            lines.append("")
        lines += [
            f"\tpartition {q(table)} = m",
            "\t\tmode: import",
            "\t\tsource =",
            "\t\t\t\tlet",
            "\t\t\t\t    Source = Sql.Database(Servidor, BaseDatos),",
            f"\t\t\t\t    Tabla = Source{{[Schema=\"{schema}\",Item=\"{sql_table}\"]}}[Data]",
            "\t\t\t\tin",
            "\t\t\t\t    Tabla",
            "",
            "\tannotation PBI_ResultType = Table",
            "",
        ]
        write(d / "tables" / f"{table}.tmdl", "\n".join(lines))

    # Tabla de medidas: una tabla calculada de una fila, oculta, que solo agrupa las medidas.
    lines = ["/// Todas las medidas del reporte, agrupadas por pagina en carpetas.", "table Medidas",
             f"\tlineageTag: {tag('t', 'Medidas')}", ""]
    for folder, name, expr, fmt, desc in MEASURES:
        lines.append(f"\t/// {desc}")
        if "\n" in expr:
            lines.append(f"\tmeasure {q(name)} =")
            lines += ["\t\t\t" + l for l in expr.split("\n")]
        else:
            lines.append(f"\tmeasure {q(name)} = {expr}")
        lines.append(f"\t\tformatString: {fmt}")
        lines.append(f"\t\tdisplayFolder: {folder}")
        lines.append(f"\t\tlineageTag: {tag('m', name)}")
        lines.append("")
    lines += ["\tcolumn _", "\t\tdataType: int64", "\t\tisHidden", "\t\tformatString: 0",
              f"\t\tlineageTag: {tag('c', 'Medidas', '_')}", "\t\tsummarizeBy: none",
              "\t\tisNameInferred", "\t\tsourceColumn: [_]", "",
              "\tpartition Medidas = calculated", "\t\tmode: import", "\t\tsource = ROW(\"_\", 0)", "",
              "\tannotation PBI_Id = medidas", ""]
    write(d / "tables" / "Medidas.tmdl", "\n".join(lines))

    rels = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        rels += [f"relationship {tag('r', ft, fc, tt, tc)}",
                 f"\tfromColumn: {q(ft)}.{q(fc)}", f"\ttoColumn: {q(tt)}.{q(tc)}", ""]
    write(d / "relationships.tmdl", "\n".join(rels))


# --------------------------------------------------------------------------------------
# Reporte PBIR
# --------------------------------------------------------------------------------------
GREEN, GOLD, INK, MUTED = "#1F5C2E", "#E3A21A", "#1D2B22", "#5B6B60"


def lit(v) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def measure(name: str) -> dict:
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Medidas"}}, "Property": name}},
            "queryRef": f"Medidas.{name}", "nativeQueryRef": name}


def column(table: str, name: str) -> dict:
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}},
            "queryRef": f"{table}.{name}", "nativeQueryRef": name}


def container(vid: str, x, y, w, h, z, visual: dict) -> dict:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": vid, "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": visual,
    }


def title_obj(text: str) -> dict:
    return {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{text}'"),
                                      "fontSize": lit("12D"), "fontColor": {"solid": {"color": lit(f"'{INK}'")}}}}]}


def textbox(text: str, size: str, color: str, bold: bool = False, extra: list | None = None) -> dict:
    runs = [{"value": text, "textStyle": {"fontFamily": "Segoe UI Semibold" if bold else "Segoe UI",
                                          "fontSize": size, "color": color}}]
    paragraphs = [{"textRuns": runs}]
    for t, s, c in extra or []:
        paragraphs.append({"textRuns": [{"value": t, "textStyle": {"fontFamily": "Segoe UI", "fontSize": s, "color": c}}]})
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "drillFilterOtherVisuals": True}


def card(measures: list[str]) -> dict:
    return {
        "visualType": "cardVisual",
        "query": {"queryState": {"Data": {"projections": [measure(m) for m in measures]}}},
        "objects": {
            "layout": [{"properties": {"orientation": lit("0D"), "columnCount": lit(f"{len(measures)}L"),
                                       "alignment": lit("'middle'"), "style": lit("'Cards'")}}],
            "value": [{"properties": {"fontSize": lit("26D"), "labelDisplayUnits": lit("1D"),
                                      "fontColor": {"solid": {"color": lit(f"'{GREEN}'")}}},
                       "selector": {"id": "default"}}],
            "accentBar": [{"properties": {"show": lit("true"),
                                          "color": {"solid": {"color": lit(f"'{GOLD}'")}}},
                           "selector": {"id": "default"}}],
        },
        "visualContainerObjects": {"title": [{"properties": {"show": lit("false")}}]},
        "drillFilterOtherVisuals": True,
    }


def chart(vtype: str, category: dict, values: list[str], title: str, sort_by: str | None = None) -> dict:
    query = {"queryState": {"Category": {"projections": [{**category, "active": True}]},
                            "Y": {"projections": [measure(m) for m in values]}}}
    if sort_by:
        query["sortDefinition"] = {"sort": [{"field": measure(sort_by)["field"], "direction": "Descending"}],
                                   "isDefaultSort": True}
    axis = {"showAxisTitle": lit("false")}
    # columnas: anos como categoria (pocas mediciones); lineas: eje continuo (hasta 64 anos)
    if vtype != "lineChart" and category["field"]["Column"]["Property"] in ("anio", "periodo"):
        axis["axisType"] = lit("'Categorical'")
    objects = {"categoryAxis": [{"properties": axis}],
               "valueAxis": [{"properties": {"showAxisTitle": lit("false")}}]}
    if len(values) > 1:
        objects["legend"] = [{"properties": {"show": lit("true"), "position": lit("'Top'")}}]
    return {"visualType": vtype, "query": query, "objects": objects,
            "visualContainerObjects": title_obj(title), "drillFilterOtherVisuals": True}


def table_visual(cols: list[dict], title: str) -> dict:
    return {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": cols}}},
            "visualContainerObjects": title_obj(title), "drillFilterOtherVisuals": True}


def slicer(col: dict, title: str, mode: str = "Basic") -> dict:
    return {"visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [{**col, "active": True}]}}},
            "objects": {"data": [{"properties": {"mode": lit(f"'{mode}'")}}],
                        "header": [{"properties": {"show": lit("false")}}]},
            "visualContainerObjects": title_obj(title), "drillFilterOtherVisuals": True}


FUENTES = "Fuentes: MOCUPP (SINAC/PNUD, CENAT-PRIAS), IGN, UN Comtrade (HS 080430), FAOSTAT. Pipeline y validaciones: github.com/bryamslm/observatorio-pina"

PAGES = [
    ("mercado", "1 · Mercado", "Costa Rica en el mercado mundial de la piña",
     "Exportaciones FOB, destinos y cuota mundial. El volumen de 2024 se excluye: Comtrade reporta casi el doble que 2023.",
     ["Exportaciones USD (último año)", "Cuota mundial CR %", "Precio USD por caja de 12 kg", "Var % exportaciones a/a"],
     [("lineChart", column("Año", "anio"), ["Exportaciones USD"], "Exportaciones de Costa Rica por año (USD)", None),
      ("clusteredBarChart", column("País", "pais"), ["Exportaciones USD (último año)"],
       "Destinos en el último año (USD)", "Exportaciones USD (último año)")],
     slicer(column("Año", "anio"), "Año", "Between")),
    ("territorio", "2 · Territorio", "Dónde está la piña",
     "Hectáreas por distrito según MOCUPP (2000, 2015, 2017-2019). La capa 2016 se excluye: está incompleta.",
     ["Hectáreas de piña", "Participación Huetar Norte %", "Crecimiento ha 2000-2019"],
     [("clusteredColumnChart", column("Año", "anio"), ["Hectáreas de piña"], "Área de piña por medición (ha)", None),
      ("clusteredBarChart", column("Distrito", "distrito"), ["Hectáreas de piña"],
       "Distritos con más piña, última medición (ha)", "Hectáreas de piña")],
     slicer(column("Distrito", "canton"), "Cantón")),
    ("sostenibilidad", "3 · Sostenibilidad", "Piña y bosque",
     "Cobertura arbórea convertida a piña por periodo. 2000-2015 abarca quince años; los demás, uno.",
     ["Ha pérdida de bosque", "Pérdida último periodo (ha)", "% del área con pérdida"],
     [("clusteredColumnChart", column("Cambio cobertura", "periodo"), ["Ha pérdida de bosque"],
       "Pérdida de bosque asociada a piña por periodo (ha)", None),
      ("clusteredBarChart", column("Distrito", "distrito"), ["Ha pérdida de bosque"],
       "Distritos con más pérdida (ha)", "Ha pérdida de bosque")],
     slicer(column("Cambio cobertura", "periodo"), "Periodo")),
    ("productividad", "4 · Productividad", "Rendimiento: Costa Rica contra el mundo",
     "Toneladas por hectárea cosechada según FAOSTAT. Los agregados regionales se excluyen de los rankings.",
     ["Rendimiento CR t/ha (último año)", "Rendimiento mundial t/ha (último año)", "Producción CR t (último año)"],
     [("lineChart", column("Año", "anio"), ["Rendimiento CR t/ha", "Rendimiento mundial t/ha"],
       "Rendimiento por año (t/ha)", None),
      ("clusteredBarChart", column("País", "pais"), ["Producción t (último año)"],
       "Mayores productores, último año (t)", "Producción t (último año)")],
     slicer(column("Año", "anio"), "Año", "Between")),
    ("operacion", "5 · Operación (simulada)", "Operación de finca · DATOS SIMULADOS",
     "No son datos de ninguna empresa. Precio calibrado con Comtrade 2023; costo de campo con la referencia del MAG.",
     ["Cajas por ha por ciclo", "% exportable", "Costo por caja exportable CRC", "Margen de campo USD/caja"],
     [("clusteredBarChart", column("Bloque", "cod_bloque"), ["Desviación vs presupuesto %"],
       "Desviación del costo contra presupuesto por bloque", "Desviación vs presupuesto %"),
      ("clusteredColumnChart", column("Labores", "labor"), ["Costo real CRC", "Costo presupuesto CRC"],
       "Costo real vs presupuesto por labor (CRC)", None)],
     slicer(column("Bloque", "finca"), "Finca")),
]


def report():
    rp = OUT / f"{NAME}.Report"
    write(rp / "definition.pbir", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2))
    d = rp / "definition"
    write(d / "version.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0"}, indent=2))
    write(d / "report.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.0.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY24SU10", "reportVersionAtImport": {"visual": "1.8.97", "report": "2.0.97", "page": "1.3.97"},
                          "type": "SharedResources"},
            "customTheme": {"name": "observatorio.json", "reportVersionAtImport": {"visual": "1.8.100", "report": "2.0.100", "page": "1.3.100"},
                            "type": "RegisteredResources"}},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "observatorio.json", "path": "observatorio.json", "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultFilterActionIsDataFilter": True,
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True},
    }, indent=2))
    write(rp / "StaticResources" / "RegisteredResources" / "observatorio.json", json.dumps({
        "name": "Observatorio piña",
        "dataColors": [GREEN, GOLD, "#5E8C61", "#B5651D", "#2E7D6B", "#C9B458", "#7A5C3E", "#8FB996"],
        "background": "#FBFAF5", "foreground": INK, "tableAccent": GREEN,
        "maximum": GREEN, "center": GOLD, "minimum": "#F3EFE0",
    }, indent=2, ensure_ascii=False))

    write(d / "pages" / "pages.json", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p[0] for p in PAGES], "activePageName": PAGES[0][0]}, indent=2))

    for pid, display, heading, subtitle, cards, charts, page_slicer in PAGES:
        pdir = d / "pages" / pid
        write(pdir / "page.json", json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.4.0/schema.json",
            "name": pid, "displayName": display, "displayOption": "FitToPage", "height": 720, "width": 1280,
            "objects": {"background": [{"properties": {"color": {"solid": {"color": lit("'#FBFAF5'")}},
                                                       "transparency": lit("0D")}}]},
        }, indent=2, ensure_ascii=False))
        heading_color = "#9A2B1B" if pid == "operacion" else INK
        visuals = {
            "titulo": container(f"{pid}titulo", 24, 12, 960, 76, 1000,
                                textbox(heading, "22pt", heading_color, True, [(subtitle, "10pt", MUTED)])),
            "filtro": container(f"{pid}filtro", 1000, 16, 256, 76, 2000, page_slicer),
            "tarjetas": container(f"{pid}tarjetas", 24, 100, 1232, 120, 3000, card(cards)),
            "fuentes": container(f"{pid}fuentes", 24, 684, 1232, 28, 9000, textbox(FUENTES, "8pt", MUTED)),
        }
        (vt1, cat1, val1, t1, s1), (vt2, cat2, val2, t2, s2) = charts
        visuals["grafico1"] = container(f"{pid}grafico1", 24, 236, 700, 440, 4000, chart(vt1, cat1, val1, t1, s1))
        visuals["grafico2"] = container(f"{pid}grafico2", 740, 236, 516, 440, 5000, chart(vt2, cat2, val2, t2, s2))
        for vid, v in visuals.items():
            write(pdir / "visuals" / vid / "visual.json", json.dumps(v, indent=2, ensure_ascii=False))


def main():
    if OUT.exists():
        # se conserva cualquier .pbix guardado a mano; se regenera solo el proyecto
        for p in OUT.glob(f"{NAME}.*"):
            if p.is_dir():
                shutil.rmtree(p)
    OUT.mkdir(exist_ok=True)
    semantic_model()
    report()
    write(OUT / f"{NAME}.pbip", json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2))
    n_vis = sum(1 for _ in (OUT / f"{NAME}.Report").rglob("visual.json"))
    print(f"PBIP generado en {OUT}: {len(TABLES) + 1} tablas, {len(RELATIONSHIPS)} relaciones, "
          f"{len(MEASURES)} medidas, {len(PAGES)} paginas, {n_vis} visuales")


if __name__ == "__main__":
    main()
