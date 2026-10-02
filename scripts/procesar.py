"""
Convierte data/raw/ en el modelo estrella de data/clean/ (CSV UTF-8, listo para
Power BI y para PostgreSQL).

    python scripts/procesar.py

Dimensiones: dim_distrito, dim_pais, dim_anio
Hechos:      fact_area_pina          (ha de pina por distrito y ano, MOCUPP)
             fact_cambio_cobertura   (transiciones de uso por distrito y periodo, MOCUPP)
             fact_export_cr          (exportaciones de CR por destino y ano, Comtrade)
             fact_export_mundo       (exportaciones de cada pais al mundo, Comtrade)
             fact_produccion         (area cosechada, produccion y rendimiento, FAOSTAT)

Decisiones que afectan las cifras (ver docs/calidad-de-datos.md):
- El WFS de MOCUPP declara EPSG:4326 pero las coordenadas son CRTM05 (EPSG:5367).
  Se fuerza 5367; con eso el area de 2015 y 2018 coincide con la publicada.
- La capa Pina_2016 esta incompleta (5.959 ha contra 68.643 publicadas): se excluye.
"""
import json
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
CRTM05 = 5367

AREA_YEARS = [2000, 2015, 2017, 2018, 2019]
CHANGE_PERIODS = ["2000_2015", "2015_2016", "2016_2017", "2017_2018", "2018_2019"]


def norm(text: str) -> str:
    """'Región' -> 'region'. Los nombres de columna del WFS vienen con tildes variables."""
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()


def read_layer(path: Path) -> gpd.GeoDataFrame:
    g = gpd.read_file(path).set_crs(CRTM05, allow_override=True)
    g.columns = [norm(c) for c in g.columns]
    g = g.set_geometry("geometry")
    g["geometry"] = g.geometry.force_2d().make_valid()
    return g


def mocupp_file(prefix: str, suffix: str) -> Path:
    # "Pina_2019" se publico como "Piña_2019": se busca sin depender de la tilde.
    return next(p for p in (RAW / "mocupp").glob("*.geojson")
                if norm(p.stem) == norm(f"{prefix}_{suffix}"))


def districts() -> gpd.GeoDataFrame:
    d = read_layer(RAW / "limites" / "limitedistrital_5k.geojson")
    # "codigo" no es unico (Chomes y San Juan de Abangares comparten 160105);
    # el codigo DTA (provincia-canton-distrito) si lo es.
    d = d.rename(columns={"codigo_dta": "cod_distrito", "codigo_canton": "cod_canton",
                          "codigo_provincia": "cod_provincia"})
    d["cod_distrito"] = d["cod_distrito"].astype(int)
    assert d["cod_distrito"].is_unique, "codigo DTA duplicado"
    d["area_distrito_ha"] = d.area / 1e4
    return d[["cod_distrito", "provincia", "canton", "distrito", "cod_canton",
              "cod_provincia", "region", "area_distrito_ha", "geometry"]]


def change_label(label: str) -> str:
    """Cada entrega rotula distinto ('Sin cambi', 'Sin cambios en paisaje productivo', 'Perdida de CA')."""
    n = norm(label)
    if n.startswith("perdida"):
        return "perdida_cobertura_arborea"
    if n.startswith("sin cambi"):
        return "sin_cambio"
    return "otros_cambios"


def area_by_district(layer: gpd.GeoDataFrame, dist: gpd.GeoDataFrame, keep: list[str]) -> pd.DataFrame:
    """Corta cada poligono por los limites distritales y suma hectareas."""
    inter = gpd.overlay(layer[keep + ["geometry"]], dist[["cod_distrito", "geometry"]],
                        how="intersection", keep_geom_type=True)
    inter["ha"] = inter.area / 1e4
    return inter.groupby(["cod_distrito"] + keep, as_index=False)["ha"].sum()


def build_mocupp(dist: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for year in AREA_YEARS:
        g = read_layer(mocupp_file("Pina", str(year)))
        a = area_by_district(g, dist, [])
        a["anio"] = year
        rows.append(a)
        print(f"area {year}: {g.area.sum() / 1e4:,.2f} ha nacionales, "
              f"{a['ha'].sum():,.2f} ha asignadas a distritos")
    area = pd.concat(rows)[["anio", "cod_distrito", "ha"]]

    rows = []
    for period in CHANGE_PERIODS:
        g = read_layer(mocupp_file("Perdida_ganancia", period))
        start, end = period.split("_")
        # Nombres de columna distintos en cada entrega: cober2015 / cober_2015, cambio / categoria.
        g = g.rename(columns={c: "cober_desde" for c in g.columns if c.replace("_", "") == f"cober{start}"})
        g = g.rename(columns={c: "cober_hasta" for c in g.columns if c.replace("_", "") == f"cober{end}"})
        raw_label = g["cambio"] if "cambio" in g.columns else g["categoria"]
        g["tipo_cambio"] = raw_label.map(change_label)
        c = area_by_district(g, dist, ["cober_desde", "cober_hasta", "tipo_cambio"])
        c["periodo"] = f"{start}-{end}"
        c["anio_desde"], c["anio_hasta"] = int(start), int(end)
        rows.append(c)
    change = pd.concat(rows)[["periodo", "anio_desde", "anio_hasta", "cod_distrito",
                              "cober_desde", "cober_hasta", "tipo_cambio", "ha"]]
    return area, change


def build_comtrade() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ref = json.loads((RAW / "comtrade" / "ref_partnerAreas.json").read_text(encoding="utf-8"))["results"]
    countries = pd.DataFrame(ref)[["PartnerCode", "PartnerDesc", "PartnerCodeIsoAlpha3"]]
    countries.columns = ["cod_pais", "pais", "iso3"]
    countries = countries.drop_duplicates("cod_pais")
    # Comtrade conserva nombres historicos ("India (...1974)") en codigos que FAO usa hoy.
    countries["pais"] = countries["pais"].str.replace(r"\s*\(\.\.\.\d{4}\)", "", regex=True)

    def load(prefix: str) -> pd.DataFrame:
        frames = [pd.DataFrame(json.loads(p.read_text(encoding="utf-8")))
                  for p in sorted((RAW / "comtrade").glob(f"{prefix}_*.json"))]
        df = pd.concat([f for f in frames if len(f)])
        # Una fila por reporter/partner/ano: el preview ya viene agregado
        # (customsCode C00, motCode 0, partner2Code 0); se filtra por si cambia.
        df = df[(df["customsCode"] == "C00") & (df["motCode"] == 0) & (df["partner2Code"] == 0)]
        return df

    cr = load("cr_destinos")
    cr = cr[cr["partnerCode"] != 0]  # 0 = Mundo; el total se calcula en el modelo
    export_cr = cr.rename(columns={"refYear": "anio", "partnerCode": "cod_pais",
                                   "primaryValue": "usd", "netWgt": "kg"})[["anio", "cod_pais", "usd", "kg"]]

    world = load("mundo_exportadores")
    export_world = world.rename(columns={"refYear": "anio", "reporterCode": "cod_pais",
                                         "primaryValue": "usd", "netWgt": "kg"})[["anio", "cod_pais", "usd", "kg"]]
    return export_cr, export_world, countries


def build_faostat() -> pd.DataFrame:
    f = pd.read_csv(RAW / "faostat" / "faostat_pina.csv")
    f = f[f["Area Code (M49)"].str.lstrip("'").str.isdigit()]
    f["cod_pais"] = f["Area Code (M49)"].str.lstrip("'").astype(int)
    element = {"Area harvested": "area_cosechada_ha", "Production": "produccion_t", "Yield": "rendimiento_kg_ha"}
    f = f[f["Element"].isin(element)]
    wide = f.pivot_table(index=["Year", "cod_pais", "Area"], columns="Element", values="Value").reset_index()
    wide = wide.rename(columns={**element, "Year": "anio", "Area": "pais_fao"})
    return wide


def main():
    CLEAN.mkdir(parents=True, exist_ok=True)
    dist = districts()
    area, change = build_mocupp(dist)
    export_cr, export_world, countries = build_comtrade()
    production = build_faostat()

    # Agregados (Mundo, regiones FAO) quedan fuera de dim_pais para no duplicar sumas.
    codes = set(export_cr["cod_pais"]) | set(export_world["cod_pais"]) | set(production["cod_pais"])
    dim_pais = countries[countries["cod_pais"].isin(codes)]
    missing = codes - set(dim_pais["cod_pais"])
    if missing:
        names = production.drop_duplicates("cod_pais").set_index("cod_pais")["pais_fao"]
        extra = pd.DataFrame({"cod_pais": sorted(missing)})
        extra["pais"] = extra["cod_pais"].map(names)
        dim_pais = pd.concat([dim_pais, extra])

    # Agregados FAO (Mundo, continentes, regiones): Area Code >= 5000. Se marcan para que
    # el tablero no los sume ni los rankee como si fueran paises.
    fao = pd.read_csv(RAW / "faostat" / "faostat_pina.csv")
    aggregates = set(fao.loc[fao["Area Code"] >= 5000, "Area Code (M49)"].str.lstrip("'").astype(int))
    dim_pais["es_agregado"] = dim_pais["cod_pais"].isin(aggregates).astype(int)

    years = range(int(production["anio"].min()), int(max(export_world["anio"].max(), production["anio"].max())) + 1)
    dim_anio = pd.DataFrame({"anio": list(years)})

    out = {
        "dim_distrito": dist.drop(columns="geometry"),
        "dim_pais": dim_pais,
        "dim_anio": dim_anio,
        "fact_area_pina": area,
        "fact_cambio_cobertura": change,
        "fact_export_cr": export_cr,
        "fact_export_mundo": export_world,
        "fact_produccion": production.drop(columns="pais_fao"),
    }
    for name, df in out.items():
        df.to_csv(CLEAN / f"{name}.csv", index=False, encoding="utf-8")
        print(f"{name}: {len(df)} filas")

    # Geometria simplificada para el mapa web (no para calculo).
    web = dist[dist["cod_distrito"].isin(area["cod_distrito"])][["cod_distrito", "distrito", "canton", "geometry"]]
    web.assign(geometry=web.geometry.simplify(50)).to_crs(4326).to_file(
        CLEAN / "distritos_pina.geojson", driver="GeoJSON")


if __name__ == "__main__":
    main()
