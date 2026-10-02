"""
Descarga las fuentes crudas del observatorio a data/raw/.

    python scripts/descargar.py            # todo
    python scripts/descargar.py mocupp     # solo una fuente

Fuentes (todas publicas, sin clave):
- mocupp:   PRIAS/CENAT, MOCUPP Pina (WFS). Poligonos de pina 2000, 2015-2019
            y perdida/ganancia de cobertura arborea. CRTM05 (EPSG:5367).
- limites:  IGN, limite distrital 1:5000 (WFS IGN_5_CO del SNIT).
- comtrade: UN Comtrade, API publica de preview. HS 080430 (pinas frescas o secas).
- faostat:  FAO, bulk de produccion de cultivos (QCL), filtrado a pina.

Cada descarga es idempotente: si el archivo ya existe, no se vuelve a bajar.
"""
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "observatorio-pina/0.1 (proyecto de portafolio; contacto: bryamlopez.com)"}

MOCUPP_WFS = "https://monitoreo.prias.cenat.ac.cr/geoserver/MonitoreoPina/wfs"
MOCUPP_LAYERS = [
    "Pina_2000", "Pina_2015", "Pina_2016", "Pina_2017", "Pina_2018", "Piña_2019",
    "Perdida_ganancia_2000_2015", "Perdida_ganancia_2015_2016", "Perdida_ganancia_2016_2017",
    "Perdida_ganancia_2017_2018", "Perdida_ganancia_2018_2019", "No_cambio_ca_piña_2018_2019",
]
IGN_WFS = "https://geos.snitcr.go.cr/be/IGN_5_CO/wfs"
COMTRADE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
FAOSTAT_BULK = "https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip"

CR = 188          # codigo M49 de Costa Rica en Comtrade
HS_PINA = "080430"
YEARS = range(2000, 2026)


def wfs_all(url: str, layer: str, page: int = 1000) -> dict:
    """Pagina un GetFeature hasta traer todas las entidades de la capa."""
    features, start = [], 0
    while True:
        r = requests.get(url, headers=UA, timeout=180, params={
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": layer, "outputFormat": "application/json",
            "count": page, "startIndex": start,
        })
        r.raise_for_status()
        batch = r.json()["features"]
        features += batch
        if len(batch) < page:
            break
        start += page
    return {"type": "FeatureCollection", "features": features}


def mocupp():
    out = RAW / "mocupp"
    out.mkdir(parents=True, exist_ok=True)
    for layer in MOCUPP_LAYERS:
        target = out / f"{layer}.geojson"
        if target.exists():
            continue
        fc = wfs_all(MOCUPP_WFS, f"MonitoreoPina:{layer}")
        target.write_text(json.dumps(fc), encoding="utf-8")
        print(f"mocupp {layer}: {len(fc['features'])} poligonos")


def limites():
    target = RAW / "limites" / "limitedistrital_5k.geojson"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fc = wfs_all(IGN_WFS, "IGN_5_CO:limitedistrital_5k")
    target.write_text(json.dumps(fc), encoding="utf-8")
    print(f"limites distritales: {len(fc['features'])}")


def comtrade():
    """
    Dos consultas por ano:
    - cr_destinos: exportaciones de Costa Rica por pais de destino.
    - mundo_exportadores: exportaciones de cada pais al mundo (para cuota de mercado).
    La API de preview no pide clave pero limita la frecuencia: se espera entre llamadas.
    """
    out = RAW / "comtrade"
    out.mkdir(parents=True, exist_ok=True)
    for year in YEARS:
        for name, params in (
            ("cr_destinos", {"reporterCode": CR, "flowCode": "X"}),
            ("mundo_exportadores", {"partnerCode": 0, "flowCode": "X"}),
        ):
            target = out / f"{name}_{year}.json"
            if target.exists():
                continue
            r = requests.get(COMTRADE, headers=UA, timeout=120,
                             params={**params, "cmdCode": HS_PINA, "period": year})
            if r.status_code == 429:
                time.sleep(10)
                r = requests.get(COMTRADE, headers=UA, timeout=120,
                                 params={**params, "cmdCode": HS_PINA, "period": year})
            r.raise_for_status()
            data = r.json().get("data", [])
            target.write_text(json.dumps(data), encoding="utf-8")
            print(f"comtrade {name} {year}: {len(data)} filas")
            time.sleep(1.5)


def faostat():
    target = RAW / "faostat" / "faostat_pina.csv"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    r = requests.get(FAOSTAT_BULK, headers=UA, timeout=600)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = next(n for n in z.namelist() if n.endswith("(Normalized).csv"))
        df = pd.read_csv(z.open(name), encoding="latin-1", low_memory=False)
    df = df[df["Item"] == "Pineapples"]
    df.to_csv(target, index=False, encoding="utf-8")
    print(f"faostat pina: {len(df)} filas, {df['Area'].nunique()} areas")


SOURCES = {"mocupp": mocupp, "limites": limites, "comtrade": comtrade, "faostat": faostat}

if __name__ == "__main__":
    for key in sys.argv[1:] or SOURCES:
        SOURCES[key]()
