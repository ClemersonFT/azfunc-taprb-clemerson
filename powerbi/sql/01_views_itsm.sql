/*
  Views analíticas de ITSM para Power BI.
  Premissa: tabelas no schema dbo. Execute no banco de destino que contém as tabelas ITSM.
  O script não altera as tabelas de origem.
*/

CREATE OR ALTER VIEW dbo.vw_bi_chamado AS
SELECT
    c.id_chamado,
    NULLIF(TRIM(c.nr_chamado), N'') AS nr_chamado,
    NULLIF(TRIM(c.ds_tipo_chamado), N'') AS tipo_chamado,
    NULLIF(TRIM(c.ds_status_chamado), N'') AS status_chamado,
    NULLIF(TRIM(c.ds_prioridade), N'') AS prioridade,
    c.dt_criacao,
    c.dt_resolucao,
    c.dt_ultima_atualizacao,
    c.id_analista_atual,
    c.id_reporter,
    c.id_categoria,
    c.id_cliente_organizacao,
    c.id_fila_atual,
    NULLIF(TRIM(c.ds_titulo), N'') AS titulo,
    NULLIF(TRIM(c.ds_descricao), N'') AS descricao,
    CASE
        WHEN c.dt_criacao IS NOT NULL AND c.dt_resolucao >= c.dt_criacao
        THEN DATEDIFF_BIG(SECOND, c.dt_criacao, c.dt_resolucao) / 60.0
        ELSE NULL
    END AS minutos_ate_resolucao,
    CASE
        WHEN c.dt_criacao IS NOT NULL AND c.dt_resolucao IS NULL
             AND SYSUTCDATETIME() >= c.dt_criacao
        THEN DATEDIFF_BIG(SECOND, c.dt_criacao, SYSUTCDATETIME()) / 60.0
        ELSE NULL
    END AS minutos_em_aberto,
    c.dt_inclusao,
    c.dt_atualizacao,
    NULLIF(TRIM(c.nm_sistema_origem), N'') AS sistema_origem,
    NULLIF(TRIM(c.cd_registro_origem), N'') AS registro_origem
FROM dbo.chamado AS c;
GO

CREATE OR ALTER VIEW dbo.vw_bi_chamado_sla AS
SELECT
    cs.id_chamado_sla,
    cs.id_chamado,
    cs.id_sla,
    CAST(cs.fl_breach AS bit) AS fl_breach,
    cs.qt_tempo_restante_minutos,
    cs.qt_tempo_decorrido_minutos,
    COALESCE(cs.qt_meta_minutos, s.qt_meta_minutos) AS qt_meta_minutos,
    cs.dt_referencia,
    NULLIF(TRIM(s.cd_sla), N'') AS cd_sla,
    NULLIF(TRIM(s.nm_sla), N'') AS nm_sla,
    cs.dt_inclusao,
    cs.dt_atualizacao
FROM dbo.chamado_sla AS cs
LEFT JOIN dbo.sla AS s ON s.id_sla = cs.id_sla;
GO

CREATE OR ALTER VIEW dbo.vw_bi_chamado_status_historico AS
SELECT
    h.id_chamado_status_historico,
    h.id_chamado,
    NULLIF(TRIM(h.ds_status_chamado), N'') AS status_chamado,
    h.dt_inicio_status,
    h.dt_fim_status,
    CASE
        WHEN h.qt_tempo_status_minutos IS NOT NULL AND h.qt_tempo_status_minutos >= 0
            THEN h.qt_tempo_status_minutos
        WHEN h.dt_inicio_status IS NOT NULL AND h.dt_fim_status >= h.dt_inicio_status
            THEN DATEDIFF_BIG(SECOND, h.dt_inicio_status, h.dt_fim_status) / 60.0
        ELSE NULL
    END AS minutos_no_status,
    h.id_analista_responsavel,
    h.id_fila,
    h.dt_inclusao,
    h.dt_atualizacao
FROM dbo.chamado_status_historico AS h;
GO

CREATE OR ALTER VIEW dbo.vw_bi_csat AS
SELECT
    ca.id_csat_avaliacao,
    ca.id_chamado,
    ca.id_analista,
    ca.nr_score,
    NULLIF(TRIM(ca.ds_comentario), N'') AS comentario,
    ca.dt_avaliacao,
    ca.dt_inclusao,
    ca.dt_atualizacao
FROM dbo.csat_avaliacao AS ca;
GO
