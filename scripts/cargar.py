"""
Carga data/clean/*.csv en SQL Server (esquema dw) y verifica los totales.

    ssh -f -N -L 14333:127.0.0.1:14333 bryam   # tunel; SQL Server solo escucha en localhost
    python scripts/cargar.py

Credenciales en .env (no versionado). La primera corrida crea la base y los logins
observatorio_etl (carga) y observatorio_bi (solo lectura, para Power BI).
"""
import re
from pathlib import Path

import pandas as pd
import pymssql

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "data" / "clean"

# Orden de carga: dimensiones antes que hechos por las llaves foraneas.
TABLES = ["dim_anio", "dim_distrito", "dim_pais", "fact_area_pina", "fact_cambio_cobertura",
          "fact_export_cr", "fact_export_mundo", "fact_produccion"]


def env() -> dict:
    return dict(l.strip().split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l)


def connect(e: dict, user: str, password: str, database: str = "master"):
    return pymssql.connect(server=e["MSSQL_HOST"], port=e["MSSQL_PORT"], user=user,
                           password=password, database=database, autocommit=True)


def ensure_database(e: dict):
    """Base y logins. Idempotente: no toca lo que ya existe."""
    with connect(e, "sa", e["MSSQL_SA_PASSWORD"]) as conn, conn.cursor() as cur:
        db = e["MSSQL_DB"]
        cur.execute(f"if db_id('{db}') is null create database {db}")
        for login, key in (("observatorio_etl", "MSSQL_ETL_PASSWORD"), ("observatorio_bi", "MSSQL_BI_PASSWORD")):
            pw = e[key].replace("'", "''")
            cur.execute(f"if suser_id('{login}') is null create login {login} with password = '{pw}', check_policy = off")
            cur.execute(f"use {db}; if user_id('{login}') is null create user {login} for login {login}")
        cur.execute(f"use {db}; alter role db_owner add member observatorio_etl")


def main():
    e = env()
    ensure_database(e)
    with connect(e, "observatorio_etl", e["MSSQL_ETL_PASSWORD"], e["MSSQL_DB"]) as conn, conn.cursor() as cur:
        script = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
        for batch in re.split(r"^\s*GO\s*$", script, flags=re.MULTILINE):
            if batch.strip():
                cur.execute(batch)

        for table in TABLES:
            df = pd.read_csv(CLEAN / f"{table}.csv")
            cols = ", ".join(df.columns)
            row_marks = "(" + ", ".join(["%s"] * len(df.columns)) + ")"
            rows = [tuple(None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in r)
                    for r in df.itertuples(index=False)]
            # Fila por fila sobre el tunel tarda minutos; un INSERT acepta hasta 1000
            # filas y 2100 parametros, asi que se agrupa respetando ambos topes.
            chunk = min(1000, 2000 // len(df.columns))
            for i in range(0, len(rows), chunk):
                part = rows[i:i + chunk]
                cur.execute(f"insert into dw.{table} ({cols}) values " + ", ".join([row_marks] * len(part)),
                            tuple(v for r in part for v in r))
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
            cur.execute(sql)
            print(f"control {label}: {cur.fetchone()[0]:,.2f}")


if __name__ == "__main__":
    main()
