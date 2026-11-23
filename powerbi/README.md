# Guia Power BI — ITSM

## 1. Preparar o banco e importar os dados

1. Confirme que as tabelas ITSM estão no banco de destino e valide o schema. O SQL em `sql/01_views_itsm.sql` assume `dbo` e somente cria views; não modifica dados de origem.
2. Execute o script no SQL Server. Valide contagem e chaves com consultas simples antes de conectar o Power BI.
3. No Power BI Desktop, use **Obter dados > SQL Server** e selecione o servidor/banco. Prefira **Importar** para um conjunto de dados de tamanho moderado; use DirectQuery se a atualização quase em tempo real for requisito e a infraestrutura suportar.
4. Importe as views `vw_bi_chamado`, `vw_bi_chamado_sla`, `vw_bi_chamado_status_historico`, `vw_bi_csat` e as dimensões: `analista`, `categoria`, `cliente_organizacao`, `fila`, `sla`, `solicitante`.
5. Não carregue `Address`, `Customer`, `Product`, tabelas de vendas, nem `csat` (tabela genérica com `Column1`/`Column2`), salvo se houver um requisito separado. Elas não fazem parte do modelo ITSM descrito.
6. Em Power Query, confira tipo e qualidade: IDs inteiros, datas como Date/DateTime, `fl_ativo` e `fl_breach` como booleanos, scores numéricos. Desative **Habilitar carga** para consultas staging se criar consultas auxiliares. Não substitua IDs ausentes por zero.

### Tratamento aplicado nas views

- Texto categórico e texto de exibição: remoção de espaços nas pontas e conversão de strings vazias em `NULL`.
- Duração de resolução: calculada apenas para datas válidas e resolução não anterior à criação; chamados sem resolução ficam fora dessa duração.
- Idade do backlog: calculada apenas para chamados sem data de resolução, usando UTC no momento da consulta. A medida é dinâmica; para análises históricas de backlog, é necessário armazenar snapshots periódicos.
- Histórico de status: prioriza a duração fornecida quando não negativa; quando ausente, calcula a diferença entre início e fim se válidos. Períodos sem data final não recebem duração calculada.
- Meta de SLA: usa a meta da associação e, se ausente, a meta cadastrada em `sla`.
- As views preservam as chaves, para permitir filtros por dimensões e evitar joins que multipliquem tickets.

## 2. Modelo e relacionamentos

Configure relacionamentos **1 para muitos**, direção de filtro única da dimensão para o fato, ativos salvo indicação abaixo. Confirme unicidade e FKs reais antes de publicar.

| Um (dimensão) | Muitos (fato) | Observação |
|---|---|---|
| `analista[id_analista]` | `vw_bi_chamado[id_analista_atual]` | Responsável atual |
| `categoria[id_categoria]` | `vw_bi_chamado[id_categoria]` | Categoria atual |
| `cliente_organizacao[id_cliente_organizacao]` | `vw_bi_chamado[id_cliente_organizacao]` | Organização |
| `fila[id_fila]` | `vw_bi_chamado[id_fila_atual]` | Fila atual |
| `solicitante[id_solicitante]` | `vw_bi_chamado[id_reporter]` | Confirmar que `id_reporter` referencia solicitante |
| `sla[id_sla]` | `vw_bi_chamado_sla[id_sla]` | Cadastro da meta |
| `vw_bi_chamado[id_chamado]` | `vw_bi_chamado_sla[id_chamado]` | 1:N; relação da fato ticket à fato SLA |
| `vw_bi_chamado[id_chamado]` | `vw_bi_chamado_status_historico[id_chamado]` | 1:N; relação da fato ticket ao histórico |
| `vw_bi_chamado[id_chamado]` | `vw_bi_csat[id_chamado]` | 1:N; relação da fato ticket à avaliação |
| `analista[id_analista]` | `vw_bi_csat[id_analista]` | Analista avaliado, se essa for a semântica da FK |
| `analista[id_analista]` | `vw_bi_chamado_status_historico[id_analista_responsavel]` | Analista responsável no evento; pode exigir relação inativa/role-playing |
| `fila[id_fila]` | `vw_bi_chamado_status_historico[id_fila]` | Fila no evento; pode exigir relação inativa/role-playing |

Não conecte dimensões diretamente umas às outras nem use filtro bidirecional para resolver ambiguidades. Para analisar simultaneamente responsável atual e responsável histórico, crie dimensões duplicadas (por exemplo, `Analista Atual` e `Analista do Histórico`) no Power Query, ou deixe uma das relações inativa e use `USERELATIONSHIP` em medidas específicas.

### Calendário

Crie esta tabela calculada, ajuste o intervalo se os dados estiverem fora dele e marque-a como **Tabela de datas** usando `[Date]`:

```DAX
Calendario =
VAR DatasChamado =
    FILTER (
        UNION (
            SELECTCOLUMNS ( 'vw_bi_chamado', "Dia", DATEVALUE ( 'vw_bi_chamado'[dt_criacao] ) ),
            SELECTCOLUMNS ( 'vw_bi_chamado', "Dia", DATEVALUE ( 'vw_bi_chamado'[dt_resolucao] ) )
        ),
        NOT ISBLANK ( [Dia] )
    )
VAR Inicio = MINX ( DatasChamado, [Dia] )
VAR Fim = MAXX ( DatasChamado, [Dia] )
RETURN
ADDCOLUMNS (
    CALENDAR ( Inicio, Fim ),
    "Ano", YEAR ( [Date] ),
    "Mês número", MONTH ( [Date] ),
    "Mês", FORMAT ( [Date], "mmm" ),
    "Ano-Mês", FORMAT ( [Date], "yyyy-MM" ),
    "Trimestre", "T" & FORMAT ( [Date], "Q" )
)
```

Crie uma relação ativa `Calendario[Date]` → `vw_bi_chamado[dt_criacao]` (tipo Date; crie uma coluna de data sem hora no Power Query se necessário). Para a data de resolução, crie outra relação inativa com `vw_bi_chamado[dt_resolucao]`; use uma medida com `USERELATIONSHIP` quando for analisar resoluções por data. Para SLA e CSAT, relacione o calendário às datas `dt_referencia` e `dt_avaliacao`; se o mesmo calendário precisar filtrar várias datas ao mesmo tempo, mantenha apenas um caminho ativo e use medidas/role-playing calendars para as demais datas.

Coloque as medidas de `dax/medidas.dax` numa tabela `_Medidas`. Formate percentuais como porcentagem, tempos como decimal com uma casa e CSAT de acordo com a escala real encontrada nos dados. Não assuma que score vai de 1 a 5 sem validar.

## 3. Páginas recomendadas

### Página 1 — Visão executiva

- Cartões: Chamados, Chamados abertos, Chamados resolvidos, % chamados resolvidos, CSAT médio, % violações SLA.
- Linha: chamados criados por mês (`Calendario[Ano-Mês]`).
- Colunas empilhadas: chamados por status e prioridade.
- Barras: backlog por fila e categoria.
- Segmentadores: período de criação, prioridade, tipo, categoria, fila e organização.
- Título/subtítulo deve deixar claro que o backlog atual é fotografia do momento da atualização.

### Página 2 — Operação e backlog

- Cartões: chamados abertos, idade média em aberto, chamados resolvidos, tempo médio de resolução.
- Barras: abertos por analista e fila (mostrar também sem responsável/fila).
- Matriz: fila × status, com contagem de chamados e prioridade.
- Tendência: aberturas e resoluções por mês. Para resoluções por mês, use relação inativa de calendário com a data de resolução.
- Tabela detalhada: número, título, status, prioridade, criação, analista, fila, categoria; aplique drill-through para detalhe do chamado.

### Página 3 — SLA

- Cartões: chamados com SLA, violações, % violações.
- Barras: violações por SLA, fila e prioridade.
- Dispersão ou linha: tempo decorrido versus meta, por SLA, após validar a unidade e se os campos representam acumulado ou snapshot.
- Tabela: chamado, SLA, meta, tempo decorrido, tempo restante, breach e data de referência.
- Inclua nota de que a regra de negócio de pausas/horário de atendimento não está inferida pela estrutura disponível.

### Página 4 — Satisfação (CSAT)

- Cartões: CSAT médio, avaliações, chamados avaliados.
- Linha: média de score por mês de avaliação.
- Barras: score por categoria, analista e fila (filtros chegam pelo relacionamento ao chamado; valide a interpretação de analista).
- Tabela de comentários para investigação, com acesso restrito se comentários puderem conter dados pessoais ou sensíveis.
- Não use cores de “bom/ruim” até confirmar escala e limites oficiais.

### Página 5 — Histórico de status (opcional)

- Tempo médio no status e distribuição de duração por status/fila.
- Evolução dos estados ao longo do tempo, usando `dt_inicio_status`.
- A tabela registra intervalos por chamado; não some duração sem analisar sobreposição e qualidade das datas.

## 4. Medidas complementares úteis

Para analisar resoluções pela data de resolução usando a relação inativa com `Calendario`:

```DAX
Chamados resolvidos por data de resolução =
CALCULATE (
    [Chamados resolvidos],
    USERELATIONSHIP ( 'Calendario'[Date], 'vw_bi_chamado'[Data resolução] )
)
```

Crie `Data resolução` como coluna Date (sem hora) no Power Query. A mesma técnica pode ser aplicada à data de avaliação/SLA conforme o modelo.

## 5. Segurança, atualização e validação

- Use credenciais de leitura mínimas para o dataset; não armazene senhas em arquivos do repositório.
- Proteja comentários CSAT e descrições dos chamados. Aplique RLS apenas após definir regras de acesso por organização/equipe com o responsável pelo dado.
- Configure gateway e credenciais no Power BI Service se o SQL Server não for acessível pela nuvem. Programe a atualização de acordo com as cargas (a Function extrai de hora em hora e carrega o destino diariamente às 02h, segundo o código fornecido).
- Confira reconciliação entre SQL e Power BI: `COUNT(*)` vs Chamados; chamados sem dimensões; duplicidade de `id_chamado`; FKs órfãs; datas de resolução anteriores à criação; valores distintos de status/prioridade; e registros com `fl_breach` nulo.
- O SLA é associado ao chamado por uma relação 1:N. Medidas de tickets devem contar `DISTINCTCOUNT(id_chamado)` quando usadas no contexto da tabela SLA, para evitar dupla contagem.
- Teste filtros cruzados, totais e intervalos temporais com usuários do processo antes de publicar.
