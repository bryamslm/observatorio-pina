-- Esquema ops: operacion SIMULADA de una finca (estructura tipo Panal 360 + Business Central).
-- No son datos de ninguna empresa. Ver scripts/simular_operacion.py.

if schema_id('ops') is not null
begin
  declare @sql nvarchar(max) = N'';
  select @sql += N'drop view ops.' + quotename(name) + N';' from sys.views where schema_id = schema_id('ops');
  exec sp_executesql @sql;
  set @sql = N'';
  select @sql += N'drop table ops.' + quotename(name) + N';' from sys.tables
  where schema_id = schema_id('ops') order by case when name like 'fact%' then 0 else 1 end;
  exec sp_executesql @sql;
  drop schema ops;
end
GO
create schema ops;
GO

create table ops.dim_fecha (
  fecha  date not null primary key,
  anio   int  not null,
  mes    int  not null,
  semana int  not null
);

create table ops.dim_bloque (
  cod_bloque    nvarchar(10)  not null primary key,
  finca         nvarchar(40)  not null,
  ha            decimal(8,2)  not null,
  fecha_siembra date          not null,
  variedad      nvarchar(20)  not null
);

create table ops.dim_ciclo (
  ciclo_id       nvarchar(16) not null primary key,
  cod_bloque     nvarchar(10) not null references ops.dim_bloque,
  fecha_siembra  date         not null,
  inicio_cosecha date         not null,
  completo       bit          not null   -- todo el ciclo cae en el periodo: base de los KPI de costo
);

create table ops.parametros (
  parametro nvarchar(40)  not null primary key,
  valor     decimal(12,4) not null
);

-- Cosecha por bloque, dia y calibre (frutas por caja). calibre null = rechazo.
create table ops.fact_cosecha (
  fecha             date         not null references ops.dim_fecha,
  cod_bloque        nvarchar(10) not null references ops.dim_bloque,
  ciclo_id          nvarchar(16) not null references ops.dim_ciclo,
  calibre           int          null,
  cajas_exportables int          not null,
  cajas_rechazo     int          not null
);

-- Labores por bloque (lo que registraria un sistema de gestion agricola).
create table ops.fact_labores (
  fecha                 date          not null references ops.dim_fecha,
  cod_bloque            nvarchar(10)  not null references ops.dim_bloque,
  ciclo_id              nvarchar(16)  not null references ops.dim_ciclo,
  labor                 nvarchar(40)  not null,
  jornales              decimal(10,1) not null,
  costo_real_crc        decimal(16,0) not null,
  costo_presupuesto_crc decimal(16,0) not null
);

-- Ventas por embarque (lo que registraria el ERP).
create table ops.fact_ventas (
  fecha      date          not null references ops.dim_fecha,
  cliente    nvarchar(60)  not null,
  cod_bloque nvarchar(10)  not null references ops.dim_bloque,
  calibre    int           not null,
  cajas      int           not null,
  usd        decimal(14,2) not null
);
GO

-- KPI por ciclo completo: productividad, aprovechamiento, costo por caja y desviacion.
create view ops.v_kpi_ciclo as
with c as (
  select ciclo_id, sum(cajas_exportables) as exp, sum(cajas_rechazo) as rech
  from ops.fact_cosecha group by ciclo_id
), l as (
  select ciclo_id, sum(costo_real_crc) as real_crc, sum(costo_presupuesto_crc) as pres_crc
  from ops.fact_labores group by ciclo_id
)
select ci.ciclo_id, b.cod_bloque, b.finca, b.ha, ci.inicio_cosecha,
       c.exp + c.rech                                            as cajas_totales,
       round((c.exp + c.rech) / b.ha, 0)                         as cajas_por_ha,
       round(100.0 * c.exp / nullif(c.exp + c.rech, 0), 1)       as pct_exportable,
       l.real_crc,
       round(100.0 * (l.real_crc - l.pres_crc) / l.pres_crc, 1) as desviacion_pct,
       round(l.real_crc / nullif(c.exp, 0), 0)                   as costo_crc_por_caja_exp
from ops.dim_ciclo ci
join ops.dim_bloque b on b.cod_bloque = ci.cod_bloque
join c on c.ciclo_id = ci.ciclo_id
join l on l.ciclo_id = ci.ciclo_id
where ci.completo = 1;
GO

grant select on schema::ops to observatorio_bi;
