"""
Genera datos SIMULADOS de operacion de una finca pinera, con la forma de los datos
que salen de un sistema de gestion agricola (labores y costos por bloque, estilo
Panal 360) y de un ERP (ventas y embarques, estilo Business Central).

NO son datos de ninguna empresa real. Todos los parametros de abajo son supuestos
de trabajo, elegidos para que el tablero se pueda construir y probar; cada uno esta
rotulado. El tablero muestra estas paginas con la marca "DATOS SIMULADOS".

    python scripts/simular_operacion.py      # escribe data/clean/ops_*.csv
"""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"
rng = np.random.default_rng(2026)  # semilla fija: mismo resultado en cada corrida

# --- Supuestos (no son cifras de PCC ni de ninguna finca) ---------------------
FINCAS = {"Finca Norte": 24, "Finca Sur": 18}          # bloques por finca
HA_BLOQUE = (6.0, 12.0)                                 # rango de hectareas por bloque
MESES_A_COSECHA = (14, 17)                              # siembra -> primera cosecha
CAJAS_HA = (3800, 5200)                                 # cajas de 12 kg por ha y ciclo
PCT_EXPORTABLE = (0.78, 0.93)                           # resto: rechazo / industria
CALIBRES = [5, 6, 7, 8, 9, 10]                          # frutas por caja
PESO_CALIBRE = [0.06, 0.18, 0.30, 0.26, 0.14, 0.06]
PRECIO_CAJA_USD = {5: 11.0, 6: 10.5, 7: 10.0, 8: 9.5, 9: 9.0, 10: 8.5}
CLIENTES = ["Importador EE.UU. A", "Importador EE.UU. B", "Distribuidor Europa A",
            "Distribuidor Europa B", "Cadena Reino Unido"]
LABORES = {  # labor: (jornales por ha, costo CRC por jornal, insumo CRC por ha)
    "Preparacion de suelo": (6, 18000, 90000),
    "Siembra": (14, 18000, 350000),
    "Fertilizacion": (3, 18000, 120000),
    "Control biologico": (2, 18000, 60000),
    "Deshierba": (5, 18000, 0),
    "Induccion floral": (2, 18000, 40000),
    "Cosecha": (9, 20000, 0),
}
INICIO, FIN = date(2024, 1, 1), date(2026, 9, 30)
TIPO_CAMBIO_CRC_USD = 505.0  # supuesto fijo


def month_range(start: date, end: date):
    d = date(start.year, start.month, 1)
    while d <= end:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def main():
    bloques = []
    for finca, n in FINCAS.items():
        for i in range(1, n + 1):
            siembra = INICIO + timedelta(days=int(rng.integers(-560, 60)))
            bloques.append({
                "cod_bloque": f"{finca.split()[1][0]}-{i:02d}",
                "finca": finca,
                "ha": round(float(rng.uniform(*HA_BLOQUE)), 2),
                "fecha_siembra": siembra,  # primera siembra del periodo
                "variedad": "MD-2",
            })
    dim_bloque = pd.DataFrame(bloques)

    cosecha, labores, ventas = [], [], []
    ciclos = []
    for b in bloques:
        # resiembra ~20 meses despues de la siembra anterior, hasta cubrir el periodo
        siembra = b["fecha_siembra"]
        while siembra <= FIN:
            ciclos.append({**b, "fecha_siembra": siembra})
            siembra += timedelta(days=int(rng.integers(560, 640)))
    for b in ciclos:
        meses = int(rng.integers(*MESES_A_COSECHA))
        inicio_cosecha = b["fecha_siembra"] + timedelta(days=30 * meses)
        cajas_ciclo = b["ha"] * rng.uniform(*CAJAS_HA)
        pct_exp = rng.uniform(*PCT_EXPORTABLE)
        # la cosecha de un bloque se reparte en ~6 semanas
        for s in range(6):
            dia = inicio_cosecha + timedelta(days=7 * s)
            if not (INICIO <= dia <= FIN):
                continue
            cajas = cajas_ciclo * rng.dirichlet(np.ones(6))[s]
            exp = cajas * pct_exp
            por_calibre = rng.multinomial(int(exp), PESO_CALIBRE)
            for cal, n in zip(CALIBRES, por_calibre):
                cosecha.append({"fecha": dia, "cod_bloque": b["cod_bloque"], "calibre": cal,
                                "cajas_exportables": int(n), "cajas_rechazo": 0})
            cosecha.append({"fecha": dia, "cod_bloque": b["cod_bloque"], "calibre": None,
                            "cajas_exportables": 0, "cajas_rechazo": int(cajas - exp)})
            # venta del mismo lote, embarcada la semana siguiente
            for cal, n in zip(CALIBRES, por_calibre):
                if n:
                    precio = PRECIO_CAJA_USD[cal] * rng.uniform(0.9, 1.1)
                    ventas.append({"fecha": dia + timedelta(days=7), "cliente": rng.choice(CLIENTES),
                                   "cod_bloque": b["cod_bloque"], "calibre": cal, "cajas": int(n),
                                   "usd": round(n * precio, 2)})

        # labores: cada una en su momento del ciclo
        hitos = {"Preparacion de suelo": -20, "Siembra": 0, "Fertilizacion": 60,
                 "Control biologico": 120, "Deshierba": 180, "Induccion floral": 30 * (meses - 5),
                 "Cosecha": 30 * meses}
        for labor, offset in hitos.items():
            dia = b["fecha_siembra"] + timedelta(days=offset)
            if not (INICIO <= dia <= FIN):
                continue
            jornales_ha, crc_jornal, insumo_ha = LABORES[labor]
            real = rng.uniform(0.85, 1.25)  # desviacion contra presupuesto
            jornales = b["ha"] * jornales_ha * real
            labores.append({
                "fecha": dia, "cod_bloque": b["cod_bloque"], "labor": labor,
                "jornales": round(jornales, 1),
                "costo_real_crc": round(jornales * crc_jornal + b["ha"] * insumo_ha * real, 0),
                "costo_presupuesto_crc": round(b["ha"] * (jornales_ha * crc_jornal + insumo_ha), 0),
            })

    out = {
        "ops_dim_bloque": dim_bloque,
        "ops_fact_cosecha": pd.DataFrame(cosecha),
        "ops_fact_labores": pd.DataFrame(labores),
        "ops_fact_ventas": pd.DataFrame(ventas),
        "ops_dim_fecha": pd.DataFrame({"fecha": pd.date_range(INICIO, FIN + timedelta(days=7))}).assign(
            anio=lambda d: d.fecha.dt.year, mes=lambda d: d.fecha.dt.month,
            semana=lambda d: d.fecha.dt.isocalendar().week.astype(int)),
        "ops_parametros": pd.DataFrame([{"parametro": "tipo_cambio_crc_usd", "valor": TIPO_CAMBIO_CRC_USD}]),
    }
    for name, df in out.items():
        df.to_csv(CLEAN / f"{name}.csv", index=False, encoding="utf-8")
        print(f"{name}: {len(df)} filas")


if __name__ == "__main__":
    main()
