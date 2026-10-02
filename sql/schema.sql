-- Modelo estrella del observatorio en SQL Server (T-SQL), el mismo motor sobre el que
-- corre Business Central. Lo ejecuta scripts/cargar.py; es idempotente: borra y
-- recrea el esquema dw. Power BI lee las tablas dw.* y las vistas dw.v_*.
-- Los lotes se separan con GO (cargar.py los parte).

if schema_id('dw') is not null
begin
  declare @sql nvarchar(max) = N'';
  select @sql += N'drop view dw.' + quotename(name) + N';' from sys.views where schema_id = schema_id('dw');
  exec sp_executesql @sql;
  set @sql = N'';
  -- primero las llaves foraneas: asi el orden de borrado de tablas no importa
  select @sql += N'alter table dw.' + quotename(object_name(parent_object_id)) + N' drop constraint ' + quotename(name) + N';'
  from sys.foreign_keys where schema_id = schema_id('dw');
  exec sp_executesql @sql;
  set @sql = N'';
  select @sql += N'drop table dw.' + quotename(name) + N';' from sys.tables where schema_id = schema_id('dw');
  exec sp_executesql @sql;
  drop schema dw;
end
GO
create schema dw;
GO

-- Dimensiones ----------------------------------------------------------------

create table dw.dim_anio (
  anio int not null primary key
);

create table dw.dim_distrito (
  cod_distrito     int           not null primary key,  -- codigo DTA: provincia-canton-distrito
  provincia        nvarchar(60)  not null,
  canton           nvarchar(60)  not null,
  distrito         nvarchar(80)  not null,
  cod_canton       int           not null,
  cod_provincia    int           not null,
  region           nvarchar(60)  null,                  -- region de planificacion MIDEPLAN
  area_distrito_ha decimal(14,2) not null
);

create table dw.dim_pais (
  cod_pais int           not null primary key,          -- M49
  pais     nvarchar(120) not null,
  iso3     nvarchar(3)   null,
  es_agregado bit        not null   -- 1 = Mundo/continente/region FAO, no un pais
);

-- Hechos ---------------------------------------------------------------------

create table dw.fact_area_pina (
  anio         int           not null references dw.dim_anio,
  cod_distrito int           not null references dw.dim_distrito,
  ha           decimal(14,2) not null,
  primary key (anio, cod_distrito)
);

create table dw.fact_cambio_cobertura (
  periodo      nvarchar(9)   not null,
  anio_desde   int           not null references dw.dim_anio,
  anio_hasta   int           not null references dw.dim_anio,
  cod_distrito int           not null references dw.dim_distrito,
  cober_desde  nvarchar(40)  null,
  cober_hasta  nvarchar(40)  null,
  tipo_cambio  nvarchar(30)  not null
    check (tipo_cambio in ('perdida_cobertura_arborea', 'sin_cambio', 'otros_cambios')),
  ha           decimal(14,2) not null
);

create table dw.fact_export_cr (
  anio     int           not null references dw.dim_anio,
  cod_pais int           not null references dw.dim_pais,  -- pais de destino
  usd      decimal(18,2) not null,
  kg       decimal(18,2) null,
  primary key (anio, cod_pais)
);

create table dw.fact_export_mundo (
  anio     int           not null references dw.dim_anio,
  cod_pais int           not null references dw.dim_pais,  -- pais exportador
  usd      decimal(18,2) not null,
  kg       decimal(18,2) null,
  primary key (anio, cod_pais)
);

create table dw.fact_produccion (
  anio              int           not null references dw.dim_anio,
  cod_pais          int           not null references dw.dim_pais,
  area_cosechada_ha decimal(14,2) null,
  produccion_t      decimal(16,2) null,
  rendimiento_kg_ha decimal(12,2) null,
  primary key (anio, cod_pais)
);
GO

-- Vistas de KPI (la misma logica vive en DAX; aca sirve para validar el tablero) --

-- Exportaciones de CR por ano: valor, volumen, precio implicito y concentracion.
create view dw.v_export_cr_anual as
with t as (
  select anio, sum(usd) as usd, sum(kg) as kg from dw.fact_export_cr group by anio
), s as (
  select e.anio, cast(e.usd / t.usd as float) as cuota from dw.fact_export_cr e join t on t.anio = e.anio
)
select t.anio,
       t.usd,
       t.kg,
       round(t.usd / nullif(t.kg, 0), 3)          as usd_por_kg,
       round(max(s.cuota) * 100, 1)               as pct_principal_destino,
       round(sum(power(s.cuota * 100, 2)), 0)     as hhi   -- >2500 = mercado concentrado
from t join s on s.anio = t.anio
group by t.anio, t.usd, t.kg;
GO

-- Cuota y ranking de cada exportador del mundo.
create view dw.v_cuota_mundial as
select anio, cod_pais, usd,
       round(100 * usd / sum(usd) over (partition by anio), 1) as pct_mundial,
       rank() over (partition by anio order by usd desc)       as ranking
from dw.fact_export_mundo;
GO

-- Area de pina por canton y ano, con variacion contra la medicion anterior.
create view dw.v_area_canton as
with a as (
  select f.anio, d.provincia, d.canton, sum(f.ha) as ha
  from dw.fact_area_pina f join dw.dim_distrito d on d.cod_distrito = f.cod_distrito
  group by f.anio, d.provincia, d.canton
)
select a.*, a.ha - lag(a.ha) over (partition by a.provincia, a.canton order by a.anio) as var_ha
from a;
GO

-- Perdida de cobertura arborea asociada a pina, por distrito y periodo.
create view dw.v_perdida_bosque as
select c.periodo, d.canton, d.distrito, sum(c.ha) as ha_perdida
from dw.fact_cambio_cobertura c join dw.dim_distrito d on d.cod_distrito = c.cod_distrito
where c.tipo_cambio = 'perdida_cobertura_arborea'
group by c.periodo, d.canton, d.distrito;
GO

-- Acceso de solo lectura para Power BI.
grant select on schema::dw to observatorio_bi;
