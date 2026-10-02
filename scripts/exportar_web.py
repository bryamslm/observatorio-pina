"""
Exporta las series del modelo (las mismas reglas que las medidas DAX) a web/datos.json
y el mapa a web/distritos.geojson, para la pagina publica observatorio.bryamlopez.com.

    python scripts/exportar_web.py
"""
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
WEB = ROOT / "web"
CR = 188


def csv(name: str) -> pd.DataFrame:
    return pd.read_csv(CLEAN / f"{name}.csv")


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
                                         include_groups=False).round(4))

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
            "serie": anual[["anio", "usd", "usd_kg"]].to_dict("records"),
            "ultimo_anio": ultimo,
            "usd_ultimo": round(float(total_ult)),
            "var_ultimo": round(float(total_ult / anual.loc[anual["anio"] == ultimo - 1, "usd"].iloc[0] - 1), 4),
            "destinos": [{"pais": r.pais, "usd": round(r.usd), "pct": round(r.usd / total_ult, 4)}
                         for r in destinos.itertuples()],
            "cuota_mundial": [{"anio": int(k), "cuota": float(v)} for k, v in cuota.items()],
        },
        "territorio": {
            "serie": area_anual.to_dict("records"),
            "huetar_norte_pct": round(float(huetar), 4),
            "top_distritos": top_dist.to_dict("records"),
        },
        "sostenibilidad": {"perdida_por_periodo": perdida.to_dict("records")},
        "productividad": {"rendimiento": rend.to_dict("records")},
    }
    (WEB / "datos.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    # Mapa: hectareas por distrito y ano, sobre la geometria simplificada.
    geo = gpd.read_file(CLEAN / "distritos_pina.geojson")
    wide = area.pivot_table(index="cod_distrito", columns="anio", values="ha", aggfunc="sum").round(0)
    wide.columns = [f"ha_{c}" for c in wide.columns]
    geo = geo.merge(wide.reset_index(), on="cod_distrito", how="left").fillna(0)
    geo["geometry"] = geo.geometry.simplify(0.0008)
    geo.to_file(WEB / "distritos.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
    print(f"web/datos.json y web/distritos.geojson ({len(geo)} distritos, "
          f"{(WEB / 'distritos.geojson').stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
