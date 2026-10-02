-- Modelo estrella del observatorio. Lo ejecuta scripts/cargar.py (idempotente:
-- borra y recrea el esquema dw). Power BI lee las tablas dw.* y las vistas dw.v_*.

drop schema if exists dw cascade;
create schema dw;

-- Dimensiones ----------------------------------------------------------------

create table dw.dim_anio (
  anio int primary key
);

create table dw.dim_distrito (
  cod_distrito     int primary key,          -- codigo DTA: provincia-canton-distrito
  provincia        text not null,
  canton           text not null,
  distrito         text not null,
  cod_canton       int  not null,
  cod_provincia    int  not null,
  region           text,                     -- region de planificacion MIDEPLAN
  area_distrito_ha numeric(14,2) not null
);

create table dw.dim_pais (
  cod_pais int primary key,                  -- M49
  pais     text not null,
  iso3     text
);

-- Hechos ---------------------------------------------------------------------

create table dw.fact_area_pina (
  anio         int not null references dw.dim_anio,
  cod_distrito int not null references dw.dim_distrito,
  ha           numeric(14,2) not null,
  primary key (anio, cod_distrito)
);

create table dw.fact_cambio_cobertura (
  periodo      text not null,
  anio_desde   int  not null references dw.dim_anio,
  anio_hasta   int  not null references dw.dim_anio,
  cod_distrito int  not null references dw.dim_distrito,
  cober_desde  text,
  cober_hasta  text,
  tipo_cambio  text not null check (tipo_cambio in ('perdida_cobertura_arborea', 'sin_cambio', 'otros_cambios')),
  ha           numeric(14,2) not null
);

create table dw.fact_export_cr (
  anio     int not null references dw.dim_anio,
  cod_pais int not null references dw.dim_pais,   -- pais de destino
  usd      numeric(18,2) not null,
  kg       numeric(18,2),
  primary key (anio, cod_pais)
);

create table dw.fact_export_mundo (
  anio     int not null references dw.dim_anio,
  cod_pais int not null references dw.dim_pais,   -- pais exportador
  usd      numeric(18,2) not null,
  kg       numeric(18,2),
  primary key (anio, cod_pais)
);

create table dw.fact_produccion (
  anio              int not null references dw.dim_anio,
  cod_pais          int not null references dw.dim_pais,
  area_cosechada_ha numeric(14,2),
  produccion_t      numeric(16,2),
  rendimiento_kg_ha numeric(12,2),
  primary key (anio, cod_pais)
);

-- Vistas de KPI (la misma logica vive en DAX; aca sirve para validar el tablero) --

-- Exportaciones de CR por ano: valor, volumen, precio implicito y concentracion.
create view dw.v_export_cr_anual as
with t as (
  select anio, sum(usd) usd, sum(kg) kg from dw.fact_export_cr group by anio
), s as (
  select e.anio, e.usd / t.usd as cuota from dw.fact_export_cr e join t using (anio)
)
select t.anio,
       t.usd,
       t.kg,
       round(t.usd / nullif(t.kg, 0), 3)                as usd_por_kg,
       round(max(s.cuota) * 100, 1)                     as pct_principal_destino,
       round(sum(power(s.cuota * 100, 2)))              as hhi   -- >2500 = mercado concentrado
from t join s using (anio)
group by t.anio, t.usd, t.kg;

-- Cuota y ranking de CR entre los exportadores del mundo.
create view dw.v_cuota_mundial as
select anio, cod_pais, usd,
       round(100 * usd / sum(usd) over (partition by anio), 1) as pct_mundial,
       rank() over (partition by anio order by usd desc)       as ranking
from dw.fact_export_mundo;

-- Area de pina por canton y ano, con variacion contra la medicion anterior.
create view dw.v_area_canton as
with a as (
  select f.anio, d.provincia, d.canton, sum(f.ha) ha
  from dw.fact_area_pina f join dw.dim_distrito d using (cod_distrito)
  group by f.anio, d.provincia, d.canton
)
select *, ha - lag(ha) over (partition by provincia, canton order by anio) as var_ha
from a;

-- Perdida de cobertura arborea asociada a pina, por distrito y periodo.
create view dw.v_perdida_bosque as
select c.periodo, d.canton, d.distrito, sum(c.ha) as ha_perdida
from dw.fact_cambio_cobertura c join dw.dim_distrito d using (cod_distrito)
where c.tipo_cambio = 'perdida_cobertura_arborea'
group by c.periodo, d.canton, d.distrito;

-- Acceso de solo lectura para Power BI.
grant usage on schema dw to observatorio_bi;
grant select on all tables in schema dw to observatorio_bi;
