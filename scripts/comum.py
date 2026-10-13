"""comum.py — utilitários compartilhados pelos scripts de cenário."""
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

PERFIL = os.environ.get("AWS_PROFILE_DEMO", "darede-sandbox")
REGIAO = os.environ.get("AWS_REGION_DEMO", "us-east-1")
STACK = os.environ.get("STACK_DEMO", "observability-demo-dev")
AMBIENTE = "dev"

DIR_SCRIPTS = Path(__file__).resolve().parent
DIR_SAIDA = DIR_SCRIPTS / "saida"

FILAS_PRINCIPAIS = {
    "estoque": f"pedidos-estoque-{AMBIENTE}",
    "notificacao": f"pedidos-notificacao-{AMBIENTE}",
    "financeiro": f"pedidos-financeiro-{AMBIENTE}",
}
DLQS = {
    "estoque-dlq": f"pedidos-estoque-dlq-{AMBIENTE}",
    "notificacao-dlq": f"pedidos-notificacao-dlq-{AMBIENTE}",
    "financeiro-dlq": f"pedidos-financeiro-dlq-{AMBIENTE}",
    "rule-dlq": f"pedidos-rule-dlq-{AMBIENTE}",
    "processar-falhas": f"pedidos-processar-falhas-{AMBIENTE}",
}
LOG_GROUPS = {
    "criar": f"/aws/lambda/pedidos-criar-{AMBIENTE}",
    "processar": f"/aws/lambda/pedidos-processar-{AMBIENTE}",
    "estoque": f"/aws/lambda/pedidos-estoque-consumer-{AMBIENTE}",
    "notificacao": f"/aws/lambda/pedidos-notificacao-consumer-{AMBIENTE}",
    "financeiro": f"/aws/lambda/pedidos-financeiro-consumer-{AMBIENTE}",
}


def sessao():
    return boto3.Session(profile_name=PERFIL, region_name=REGIAO)


def outputs_stack(s=None):
    s = s or sessao()
    stack = s.client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def url_fila(nome, s=None):
    s = s or sessao()
    return s.client("sqs").get_queue_url(QueueName=nome)["QueueUrl"]


def agora_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ler_pedidos(cenario):
    arq = DIR_SAIDA / f"pedidos-{cenario}.txt"
    linhas = [l.strip() for l in arq.read_text().splitlines() if l.strip() and not l.startswith("#")]
    return linhas


def janela_cenario(cenario):
    """Lê o início/fim gravados no cabeçalho do arquivo de pedidos (epoch s)."""
    arq = DIR_SAIDA / f"pedidos-{cenario}.txt"
    meta = {}
    for l in arq.read_text().splitlines():
        if l.startswith("# ") and "=" in l:
            k, v = l[2:].split("=", 1)
            meta[k.strip()] = v.strip()
    return int(meta["inicio_epoch"]), meta


def insights(log_groups, query, inicio, fim=None, s=None, timeout=300):
    """Roda uma query do Logs Insights e devolve a lista de linhas como dicts."""
    s = s or sessao()
    logs = s.client("logs")
    fim = fim or int(time.time()) + 60
    if isinstance(log_groups, str):
        log_groups = [log_groups]
    qid = logs.start_query(
        logGroupNames=log_groups, startTime=int(inicio), endTime=int(fim),
        queryString=query, limit=10000,
    )["queryId"]
    t0 = time.time()
    while True:
        r = logs.get_query_results(queryId=qid)
        if r["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        if time.time() - t0 > timeout:
            raise TimeoutError(f"query {qid} não terminou em {timeout}s")
        time.sleep(2)
    if r["status"] != "Complete":
        raise RuntimeError(f"query terminou com status {r['status']}")
    return [{c["field"]: c["value"] for c in linha} for linha in r["results"]]
