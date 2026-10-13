#!/usr/bin/env python3
"""analisar.py — confere o resultado de cada cenário nos logs, métricas e DLQs.

Subcomandos:
  fanout       --cenario fanout      cada pedido_id chegou aos 4 consumidores? (cenário 0)
  visibility   --cenario visibility  pedidos processados por mais de uma invocação + EstoqueBaixado (cenário 1)
  notificacao  --cenario com-flag    classifica os pedidos da rodada (cenário 2)
  dlq          --cenario dlq         pedidos do cenário na FinanceiroDLQ + estado do alarme (cenário 3)
  espiar-dlq   --fila financeiro-dlq lista as mensagens de uma DLQ SEM apagar

Todas as leituras de DLQ usam receive-message com VisibilityTimeout=0 e nunca
chamam delete-message.
"""
import argparse
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import comum

DIR_QUERIES = comum.DIR_SCRIPTS / "queries"


def query_do_arquivo(nome, bloco=1):
    """Lê o N-ésimo bloco ```sql de scripts/queries/<nome>.md."""
    texto = (DIR_QUERIES / f"{nome}.md").read_text()
    blocos = re.findall(r"```(?:sql)?\n(.*?)```", texto, re.S)
    return blocos[bloco - 1].strip()


def espiar_dlq(nome_fila, s=None, rodadas_sem_novidade=8, max_rodadas=300):
    """Lê todas as mensagens de uma fila sem apagar. Devolve {message_id: corpo_dict}."""
    s = s or comum.sessao()
    sqs = s.client("sqs")
    url = comum.url_fila(nome_fila, s)
    aprox = int(sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])
                ["Attributes"]["ApproximateNumberOfMessages"])
    vistas, sem_novidade = {}, 0
    for _ in range(max_rodadas):
        r = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, VisibilityTimeout=0,
                                WaitTimeSeconds=1, AttributeNames=["All"])
        novas = 0
        for m in r.get("Messages", []):
            if m["MessageId"] not in vistas:
                try:
                    corpo = json.loads(m["Body"])
                except json.JSONDecodeError:
                    corpo = {"_raw": m["Body"]}
                vistas[m["MessageId"]] = corpo
                novas += 1
        sem_novidade = 0 if novas else sem_novidade + 1
        if len(vistas) >= aprox and sem_novidade >= 2:
            break
        if sem_novidade >= rodadas_sem_novidade:
            break
    return vistas, aprox


def pedido_da_msg(corpo):
    return (corpo.get("detail") or {}).get("pedido_id")


# ---------------------------------------------------------------- cenário 0
def cmd_fanout(args):
    ids = comum.ler_pedidos(args.cenario)
    inicio, _ = comum.janela_cenario(args.cenario)
    print(f"{len(ids)} pedidos em pedidos-{args.cenario}.txt")
    regex = "|".join(ids)
    q = f"fields @message | filter @message like /{regex}/ | limit 10000"
    alvos = ["processar", "estoque", "notificacao", "financeiro"]
    vistos = {}
    for alvo in alvos:
        linhas = comum.insights(comum.LOG_GROUPS[alvo], q, inicio - 60)
        vistos[alvo] = {pid for pid in ids if any(pid in l.get("@message", "") for l in linhas)}
    print(f"\n{'pedido_id':38} " + " ".join(f"{a:>11}" for a in alvos))
    for pid in ids:
        print(f"{pid:38} " + " ".join(f"{'ok' if pid in vistos[a] else 'FALTA':>11}" for a in alvos))
    print("\nTotal por consumidor: " + ", ".join(f"{a}={len(vistos[a])}/{len(ids)}" for a in alvos))

    # Resultado final de cada consumidor (não só "chegou")
    print("\nResultado por consumidor (mensagens de log de negócio):")
    q2 = query_do_arquivo("cenario0-fanout", 2)
    for alvo in alvos:
        linhas = comum.insights(comum.LOG_GROUPS[alvo], q2, inicio - 60)
        c = Counter(l["message"] for l in linhas if l.get("pedido_id") in ids)
        print(f"  {alvo:12} {dict(c)}")
    dlq, _ = espiar_dlq(comum.DLQS["financeiro-dlq"])
    na_dlq = sorted({pedido_da_msg(c) for c in dlq.values()} & set(ids))
    print(f"  financeiro na DLQ: {len(na_dlq)} {na_dlq}")


# ---------------------------------------------------------------- cenário 1
def soma_metrica(nome, inicio, fim, s=None):
    s = s or comum.sessao()
    cw = s.client("cloudwatch")
    r = cw.get_metric_statistics(
        Namespace="observability-demo/Pedidos", MetricName=nome,
        Dimensions=[{"Name": "service", "Value": "observability-demo"}],
        StartTime=datetime.fromtimestamp(inicio, timezone.utc),
        EndTime=datetime.fromtimestamp(fim, timezone.utc),
        Period=60, Statistics=["Sum"],
    )
    return sum(p["Sum"] for p in r["Datapoints"])


def cmd_visibility(args):
    ids = set(comum.ler_pedidos(args.cenario))
    inicio, meta = comum.janela_cenario(args.cenario)
    fim = int(time.time()) + 60
    print(f"Janela: {meta.get('inicio_utc')} até agora | pedidos criados: {len(ids)}")

    q = query_do_arquivo("cenario1-visibility", 1)
    print("\nQuery (Logs Insights, log group /aws/lambda/pedidos-estoque-consumer-dev):\n" + q + "\n")
    linhas = [l for l in comum.insights(comum.LOG_GROUPS["estoque"], q, inicio - 60, fim) if l.get("pedido_id") in ids]
    for l in linhas:
        print(f"  {l['pedido_id']}  invocacoes={l.get('invocacoes')}")
    print(f"\nPedidos processados por mais de uma invocação: {len(linhas)} de {len(ids)}")

    q2 = query_do_arquivo("cenario1-visibility", 2)
    tot = comum.insights(comum.LOG_GROUPS["estoque"], q2, inicio - 60, fim)
    print(f"Totais no log group (janela): {tot}")

    soma = soma_metrica("EstoqueBaixado", inicio - 60, fim)
    print(f"\nSoma de EstoqueBaixado na janela: {soma:.0f} | pedidos criados: {len(ids)} | "
          f"excesso: {soma - len(ids):+.0f}")
    print("(a métrica pode levar 1-3 min para aparecer completa no CloudWatch)")
    dlq, _ = espiar_dlq(comum.DLQS["estoque-dlq"])
    na_dlq = {pedido_da_msg(c) for c in dlq.values()} & ids
    print(f"Pedidos do cenário na EstoqueDLQ: {len(na_dlq)}")


# ---------------------------------------------------------------- cenário 2
def cmd_notificacao(args):
    ids = comum.ler_pedidos(args.cenario)
    inicio, meta = comum.janela_cenario(args.cenario)
    fim = int(time.time()) + 60
    q = query_do_arquivo("cenario2-notificacao", 1)
    linhas = comum.insights(comum.LOG_GROUPS["notificacao"], q, inicio - 60, fim)
    falhas, envios = Counter(), Counter()
    for l in linhas:
        pid = l.get("pedido_id")
        n = int(float(l.get("n", 0)))
        if l.get("message") == "Falha simulada no envio":
            falhas[pid] += n
        elif l.get("message") == "Notificação enviada ao cliente":
            envios[pid] += n

    dlq, aprox = espiar_dlq(comum.DLQS["notificacao-dlq"])
    na_dlq = Counter(pedido_da_msg(c) for c in dlq.values())

    classes = defaultdict(list)
    for pid in ids:
        f, e, d = falhas[pid], envios[pid], na_dlq[pid]
        if f == 0 and e > 0:
            classes["enviados_de_primeira"].append(pid)
        elif f > 0 and e > 0:
            classes["falharam_depois_enviados"].append(pid)
        elif f > 0 and e == 0 and d > 0:
            classes["falharam_foram_para_dlq"].append(pid)
        elif f > 0 and e == 0 and d == 0:
            classes["falharam_sumiram"].append(pid)
        else:
            classes["sem_log_nenhum"].append(pid)
    dup_envio = [pid for pid in ids if envios[pid] > 1]

    q3 = query_do_arquivo("cenario2-notificacao", 3)
    lotes = comum.insights(comum.LOG_GROUPS["notificacao"], q3, inicio - 60, fim)

    ordem = ["enviados_de_primeira", "falharam_depois_enviados", "falharam_foram_para_dlq",
             "falharam_sumiram", "sem_log_nenhum"]
    resultado = {
        "cenario": args.cenario,
        "inicio_utc": meta.get("inicio_utc"),
        "analisado_em": comum.agora_iso(),
        "pedidos_criados": len(ids),
        **{k: len(classes[k]) for k in ordem},
        "pedidos_com_falha": sum(1 for pid in ids if falhas[pid]),
        "total_logs_falha": sum(falhas[pid] for pid in ids),
        "pedidos_enviados_mais_de_uma_vez": len(dup_envio),
        "mensagens_na_dlq_total": len(dlq),
        "dlq_aproximado_sqs": aprox,
        "lotes": lotes,
        "exemplos_sumiram": classes["falharam_sumiram"][:10],
    }
    for k in ordem:
        print(f"{k:28} {len(classes[k]):4d}")
    print(json.dumps({k: v for k, v in resultado.items() if k not in ordem}, indent=2, ensure_ascii=False))
    saida = comum.DIR_SAIDA / f"notificacao-{args.cenario}.json"
    resultado["classes"] = {k: classes[k] for k in ordem}
    saida.write_text(json.dumps(resultado, indent=2, ensure_ascii=False))
    print(f"\nDetalhe gravado em {saida}")


# ---------------------------------------------------------------- cenário 3
def cmd_dlq(args):
    s = comum.sessao()
    ids = set(comum.ler_pedidos(args.cenario))
    dlq, aprox = espiar_dlq(comum.DLQS["financeiro-dlq"], s)
    por_cenario = Counter()
    todos = {}
    for c in ("fanout", "visibility", "com-flag", "sem-flag", "dlq"):
        try:
            todos[c] = set(comum.ler_pedidos(c))
        except FileNotFoundError:
            pass
    for corpo in dlq.values():
        pid = pedido_da_msg(corpo)
        origem = next((c for c, conj in todos.items() if pid in conj), "outro")
        por_cenario[origem] += 1
    print(f"FinanceiroDLQ: {len(dlq)} mensagens lidas (aprox. SQS: {aprox})")
    print(f"  por cenário de origem: {dict(por_cenario)}")
    print(f"  deste cenário ({args.cenario}): {por_cenario[args.cenario]} de {len(ids)} pedidos "
          f"({100 * por_cenario[args.cenario] / max(1, len(ids)):.0f}%)")
    al = s.client("cloudwatch").describe_alarms(AlarmNames=[f"pedidos-financeiro-dlq-com-item-{comum.AMBIENTE}"])
    for a in al["MetricAlarms"]:
        print(f"Alarme {a['AlarmName']}: {a['StateValue']} desde {a['StateUpdatedTimestamp']} — {a['StateReason']}")


def cmd_espiar(args):
    nome = comum.DLQS.get(args.fila) or comum.FILAS_PRINCIPAIS.get(args.fila) or args.fila
    dlq, aprox = espiar_dlq(nome)
    print(f"{nome}: {len(dlq)} mensagens lidas (aprox. SQS: {aprox}) — nada foi apagado")
    for mid, corpo in list(dlq.items())[:args.mostrar]:
        print(f"  {mid}  pedido_id={pedido_da_msg(corpo)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome, fn, padrao in [("fanout", cmd_fanout, "fanout"), ("visibility", cmd_visibility, "visibility"),
                             ("notificacao", cmd_notificacao, "com-flag"), ("dlq", cmd_dlq, "dlq")]:
        p = sub.add_parser(nome)
        p.add_argument("--cenario", default=padrao)
        p.set_defaults(fn=fn)
    p = sub.add_parser("espiar-dlq")
    p.add_argument("--fila", default="financeiro-dlq")
    p.add_argument("--mostrar", type=int, default=20)
    p.set_defaults(fn=cmd_espiar)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
