"""
Carga data/clean/*.csv en PostgreSQL (esquema dw) y verifica los totales.

    ssh -f -N -L 15433:127.0.0.1:5433 server   # tunel; el puerto no esta expuesto
    python scripts/cargar.py

Credenciales en .env (no versionado).
"""
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"

# Orden de carga: dimensiones antes que hechos por las llaves foraneas.
TABLES = ["dim_anio", "dim_distrito", "dim_pais", "fact_area_pina", "fact_cambio_cobertura",
          "fact_export_cr", "fact_export_mundo", "fact_produccion"]


def env() -> dict:
    return dict(l.strip().split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l)


def main():
    e = env()
    with psycopg.connect(host=e["PG_HOST"], port=e["PG_PORT"], dbname=e["PG_DB"],
                         user=e["PG_ETL_USER"], password=e["PG_ETL_PASSWORD"]) as conn:
        conn.execute((ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))
        for table in TABLES:
            df = pd.read_csv(CLEAN / f"{table}.csv")
            cols = ", ".join(df.columns)
            with conn.cursor().copy(f"copy dw.{table} ({cols}) from stdin") as copy:
                for row in df.itertuples(index=False):
                    copy.write_row([None if pd.isna(v) else v for v in row])
            print(f"dw.{table}: {len(df)} filas")

        # Mismos controles que docs/arquitectura.md, ahora contra la base.
        checks = {
            "area 2015 (pub. 58.426,11)": "select sum(ha) from dw.fact_area_pina where anio = 2015",
            "area 2018 (pub. 65.671)": "select sum(ha) from dw.fact_area_pina where anio = 2018",
            "perdida 2017-2018 (pub. 343)":
                "select sum(ha) from dw.fact_cambio_cobertura "
                "where periodo = '2017-2018' and tipo_cambio = 'perdida_cobertura_arborea'",
        }
        for label, sql in checks.items():
            print(f"control {label}: {conn.execute(sql).fetchone()[0]:,.2f}")


if __name__ == "__main__":
    main()
