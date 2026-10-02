"""
Exporta las series del modelo (las mismas reglas que las medidas DAX) a web/datos.json
y el mapa a web/distritos.geojson, para la pagina publica observatorio.bryamlopez.com.

    python scripts/exportar_web.py
"""
import json
from pathlib import Path

import sys

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
WEB = ROOT / "web"
CR = 188


def csv(name: str) -> pd.DataFrame:
    return pd.read_csv(CLEAN / f"{name}.csv")


HEX_R = 2500  # radio del hexagono en metros (CRTM05): ~16 km2 por celda


def hexbin(dist_raw: gpd.GeoDataFrame) -> dict:
    """
    Teselado hexagonal de Costa Rica con las hectareas de pina que MOCUPP detecto en
    cada celda, para 2000 y 2019. Es la firma visual de la pagina: la cascara de la pina
    hecha con los datos del cultivo.
    """
    import math

    import numpy as np
    from shapely.geometry import Polygon

    from procesar import mocupp_file, read_layer

    pais = dist_raw[dist_raw.geometry.centroid.y > 800_000]  # sin Isla del Coco
    contorno = pais.union_all().simplify(600)
    minx, miny, maxx, maxy = contorno.bounds
    w, h = math.sqrt(3) * HEX_R, 1.5 * HEX_R  # hexagonos con punta arriba
    cells = []
    for row, y in enumerate(np.arange(miny, maxy + h, h)):
        for x in np.arange(minx + (w / 2 if row % 2 else 0), maxx + w, w):
            cells.append(Polygon([(x + HEX_R * math.cos(math.radians(60 * k - 30)),
                                   y + HEX_R * math.sin(math.radians(60 * k - 30))) for k in range(6)]))
    grid = gpd.GeoDataFrame({"cell": range(len(cells))}, geometry=cells, crs=5367)
    grid = grid[grid.intersects(contorno)]

    out = grid.set_index("cell")[[]].copy()
    for year in (2000, 2019):
        pina = read_layer(mocupp_file("Pina", str(year)))[["geometry"]]
        inter = gpd.overlay(grid, pina, how="intersection", keep_geom_type=True)
        out[f"ha_{year}"] = (inter.assign(ha=inter.area / 1e4).groupby("cell")["ha"].sum())
    out = out.fillna(0)
    out = out[(out["ha_2000"] > 0) | (out["ha_2019"] > 0)]
    centers = grid.set_index("cell").loc[out.index].geometry.centroid

    def path(geom) -> str:
        polys = getattr(geom, "geoms", [geom])
        return " ".join("M" + "L".join(f"{x - minx:.0f},{maxy - y:.0f}" for x, y in p.exterior.coords) + "Z"
                        for p in polys if p.area > 5e7)

    return {
        "r": HEX_R, "ancho": round(maxx - minx), "alto": round(maxy - miny),
        "contorno": path(contorno),
        "celdas": [[round(c.x - minx), round(maxy - c.y), round(a0), round(a19)]
                   for c, a0, a19 in zip(centers, out["ha_2000"], out["ha_2019"])],
    }


def main():
    WEB.mkdir(exist_ok=True)
    pais = csv("dim_pais")
    dist = csv("dim_distrito")

    # Mercado ---------------------------------------------------------------------------
    ex = csv("fact_export_cr")
    anual = ex.groupby("anio", as_index=False)[["usd", "kg"]].sum()
    # mismas exclusiones que las medidas: el volumen 2024 no es creible
    anual["usd_kg"] = (anual["usd"] / anual["kg"]).where(anual["anio"] != 2024).round(3)
    ultimo = int(anual["anio"].max())
    destinos = (ex[ex["anio"] == ultimo].merge(pais, on="cod_pais")
                .sort_values("usd", ascending=False).head(10))
    total_ult = ex.loc[ex["anio"] == ultimo, "usd"].sum()

    mundo = csv("fact_export_mundo").merge(pais, on="cod_pais")
    mundo = mundo[(mundo["es_agregado"] == 0) & (mundo["anio"] <= 2024)]
    cuota = (mundo.groupby("anio").apply(lambda g: g.loc[g["cod_pais"] == CR, "usd"].sum() / g["usd"].sum(),
                                         include_groups=False).round(6))

    # Territorio ------------------------------------------------------------------------
    area = csv("fact_area_pina").merge(dist, on="cod_distrito")
    area_anual = area.groupby("anio", as_index=False)["ha"].sum().round(0)
    a19 = area[area["anio"] == 2019]
    huetar = a19.loc[a19["region"] == "Huetar Norte", "ha"].sum() / a19["ha"].sum()
    top_dist = a19.sort_values("ha", ascending=False).head(12)[["distrito", "canton", "ha"]].round(0)

    # Sostenibilidad --------------------------------------------------------------------
    cam = csv("fact_cambio_cobertura")
    perdida = (cam[cam["tipo_cambio"] == "perdida_cobertura_arborea"]
               .groupby("periodo", as_index=False)["ha"].sum().round(0))

    # Productividad ---------------------------------------------------------------------
    prod = csv("fact_produccion").merge(pais, on="cod_pais")
    prod = prod[prod["es_agregado"] == 0]
    g = prod.groupby("anio")[["produccion_t", "area_cosechada_ha"]].sum()
    cr = prod[prod["cod_pais"] == CR].set_index("anio")[["produccion_t", "area_cosechada_ha"]]
    rend = pd.DataFrame({
        "mundo": (g["produccion_t"] / g["area_cosechada_ha"]).round(1),
        "cr": (cr["produccion_t"] / cr["area_cosechada_ha"]).round(1),
    }).dropna().reset_index()

    datos = {
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "mercado": {
            # 2024 sin precio: NaN no es JSON valido, se exporta como null
            "serie": [{"anio": int(r.anio), "usd": round(float(r.usd)),
                       "usd_kg": None if pd.isna(r.usd_kg) else float(r.usd_kg)}
                      for r in anual.itertuples()],
            "ultimo_anio": ultimo,
            "usd_ultimo": round(float(total_ult)),
            "var_ultimo": round(float(total_ult / anual.loc[anual["anio"] == ultimo - 1, "usd"].iloc[0] - 1), 6),
            "destinos": [{"pais": r.pais, "usd": round(r.usd), "pct": round(r.usd / total_ult, 6)}
                         for r in destinos.itertuples()],
            "cuota_mundial": [{"anio": int(k), "cuota": float(v)} for k, v in cuota.items()],
        },
        "territorio": {
            "serie": area_anual.to_dict("records"),
            "huetar_norte_pct": round(float(huetar), 6),
            "top_distritos": top_dist.to_dict("records"),
        },
        "sostenibilidad": {"perdida_por_periodo": perdida.to_dict("records")},
        "productividad": {"rendimiento": rend.to_dict("records")},
        "pocosol": area[area["distrito"] == "Pocosol"].groupby("anio")["ha"].sum().round(0)
                   .reset_index().to_dict("records"),
        "hex": hexbin(gpd.read_file(ROOT / "data" / "raw" / "limites" / "limitedistrital_5k.geojson")
                      .set_crs(5367, allow_override=True)),
    }
    # allow_nan=False: falla aqui en vez de publicar un JSON que el navegador no puede leer
    (WEB / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    print(f"web/datos.json ({(WEB / 'datos.json').stat().st_size // 1024} KB, {len(datos['hex']['celdas'])} celdas)")


if __name__ == "__main__":
    main()
