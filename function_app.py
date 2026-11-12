import json
import logging
import os
from datetime import datetime, timezone
from graphlib import TopologicalSorter

import azure.functions as func
import pyodbc
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient

FONTE = "itsm"

app = func.FunctionApp()


@app.timer_trigger(
    schedule="0 0 * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_todas_tabelas(myTimer: func.TimerRequest) -> None:

    host = os.getenv("HOST")
    database = os.getenv("DATABASE")
    user = os.getenv("USER")
    password = os.getenv("PASSWORD")

    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={host};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    conn = None

    try:
        logging.info("Conectando ao banco de dados...")

        conn = pyodbc.connect(conn_str)

        logging.info("Conexão realizada com sucesso.")

        cursor = conn.cursor()

        query_tabelas = """
            SELECT TABLE_SCHEMA, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_SCHEMA, TABLE_NAME
        """

        cursor.execute(query_tabelas)

        tabelas = cursor.fetchall()

        logging.info("Quantidade de tabelas encontradas: %d", len(tabelas))

        agora = datetime.now(timezone.utc)
        blob_service = BlobServiceClient.from_connection_string(
            os.getenv("AzureWebJobsStorage")
        )
        container = blob_service.get_container_client("bronze")

        for schema, tabela in tabelas:

            logging.info("========================================")
            logging.info("Lendo tabela: %s.%s", schema, tabela)

            query = f"""
                SELECT *
                FROM [{schema}].[{tabela}]
            """

            try:
                cursor.execute(query)

                columns = [column[0] for column in cursor.description]

                rows = cursor.fetchall()

                logging.info(
                    "Tabela %s.%s possui %d registros.", schema, tabela, len(rows)
                )

                logging.info("Colunas: %s", columns)

                dados = [dict(zip(columns, row)) for row in rows]
                entidade = tabela.lower()
                caminho = (
                    f"{FONTE}/{entidade}/"
                    f"ano={agora:%Y}/mes={agora:%m}/dia={agora:%d}/"
                    f"{entidade}_{agora:%Y%m%dT%H%M%SZ}.json"
                )
                container.upload_blob(
                    name=caminho,
                    data=json.dumps(dados, default=str, ensure_ascii=False),
                    overwrite=True,
                )
                logging.info("Gravado bronze/%s (%d registros)", caminho, len(dados))

            except (pyodbc.Error, AzureError) as e:
                logging.error("Erro ao acessar %s.%s: %s", schema, tabela, e)

        cursor.close()

    except (pyodbc.Error, AzureError) as e:
        logging.error("Erro ao acessar o banco de dados: %s", e)

    except Exception as e:
        logging.exception("Erro inesperado: %s", e)

    finally:
        if conn is not None:
            conn.close()
            logging.info("Conexão com o banco de dados encerrada.")


def ordem_por_fk(cursor):
    ts = TopologicalSorter()
    cursor.execute(
        "SELECT s.name, t.name FROM sys.tables t "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id"
    )
    for schema, tabela in cursor.fetchall():
        ts.add((schema, tabela))
    cursor.execute("""
        SELECT ps.name, pt.name, rs.name, rt.name
        FROM sys.foreign_keys fk
        JOIN sys.tables pt ON pt.object_id = fk.parent_object_id
        JOIN sys.schemas ps ON ps.schema_id = pt.schema_id
        JOIN sys.tables rt ON rt.object_id = fk.referenced_object_id
        JOIN sys.schemas rs ON rs.schema_id = rt.schema_id
        WHERE pt.object_id <> rt.object_id
    """)
    for ps, pt, rs, rt in cursor.fetchall():
        ts.add((ps, pt), (rs, rt))
    return list(ts.static_order())


def ler_ultimo_json(container, entidade):
    nomes = [
        b.name for b in container.list_blobs(name_starts_with=f"{FONTE}/{entidade}/")
    ]
    if not nomes:
        return None
    return json.loads(container.download_blob(max(nomes)).readall())


def upsert(cursor, schema, tabela, dados):
    if not dados:
        return
    alvo = f"[{schema}].[{tabela}]"
    colunas = list(dados[0].keys())
    cursor.execute(
        """
        SELECT c.name FROM sys.indexes i
        JOIN sys.index_columns ic
          ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c
          ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE i.is_primary_key = 1 AND i.object_id = OBJECT_ID(?)
        """,
        alvo,
    )
    pk = [r[0] for r in cursor.fetchall()]
    cols = ", ".join(f"[{c}]" for c in colunas)
    marcas = ", ".join("?" for _ in colunas)
    on = " AND ".join(f"t.[{c}] = s.[{c}]" for c in pk)
    sets = ", ".join(f"t.[{c}] = s.[{c}]" for c in colunas if c not in pk)
    valores = ", ".join(f"s.[{c}]" for c in colunas)
    sql = (
        f"MERGE {alvo} AS t USING (VALUES ({marcas})) AS s ({cols}) ON {on} "
        + (f"WHEN MATCHED THEN UPDATE SET {sets} " if sets else "")
        + f"WHEN NOT MATCHED THEN INSERT ({cols}) VALUES ({valores});"
    )
    cursor.execute("SELECT OBJECTPROPERTY(OBJECT_ID(?), 'TableHasIdentity')", alvo)
    identity = cursor.fetchone()[0] == 1
    if identity:
        cursor.execute(f"SET IDENTITY_INSERT {alvo} ON")
    cursor.executemany(sql, [[r[c] for c in colunas] for r in dados])
    if identity:
        cursor.execute(f"SET IDENTITY_INSERT {alvo} OFF")


@app.timer_trigger(
    schedule="0 0 2 * * *",
    arg_name="loadTimer",
    run_on_startup=False,
    use_monitor=False,
)
def carregar_destino(loadTimer: func.TimerRequest) -> None:
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.getenv('DEST_HOST')};"
        f"DATABASE={os.getenv('DEST_DATABASE')};"
        f"UID={os.getenv('DEST_USER')};"
        f"PWD={os.getenv('DEST_PASSWORD')};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    container = BlobServiceClient.from_connection_string(
        os.getenv("AzureWebJobsStorage")
    ).get_container_client("bronze")

    conn = None
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        for schema, tabela in ordem_por_fk(cursor):
            dados = ler_ultimo_json(container, tabela.lower())
            if dados is None:
                logging.warning("Sem dados no bronze para %s.%s", schema, tabela)
                continue
            upsert(cursor, schema, tabela, dados)
            logging.info("Carregado %s.%s (%d registros)", schema, tabela, len(dados))
        conn.commit()
    except Exception as e:
        if conn is not None:
            conn.rollback()
        logging.exception("Erro na carga do destino: %s", e)
    finally:
        if conn is not None:
            conn.close()
