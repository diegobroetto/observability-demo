#!/usr/bin/env python3
"""aguardar_filas.py — acompanha as filas até as principais esvaziarem.

"Vazia" = ApproximateNumberOfMessages e ApproximateNumberOfMessagesNotVisible
iguais a zero em duas leituras seguidas (os números do SQS são aproximados).
As DLQs são mostradas só para acompanhamento.

Uso:
  python3 scripts/aguardar_filas.py                       # as 3 filas principais
  python3 scripts/aguardar_filas.py --filas notificacao   # só uma
  python3 scripts/aguardar_filas.py --timeout 900 --depois 300
"""
import argparse
import sys
import time

import comum

ATRIBUTOS = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible",
             "ApproximateNumberOfMessagesDelayed"]


def ler(sqs, url):
    a = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=ATRIBUTOS)["Attributes"]
    return int(a["ApproximateNumberOfMessages"]), int(a["ApproximateNumberOfMessagesNotVisible"]), \
        int(a["ApproximateNumberOfMessagesDelayed"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filas", nargs="+", choices=list(comum.FILAS_PRINCIPAIS), default=list(comum.FILAS_PRINCIPAIS))
    ap.add_argument("--timeout", type=int, default=1200, help="segundos (padrão 1200)")
    ap.add_argument("--intervalo", type=int, default=15)
    ap.add_argument("--depois", type=int, default=0,
                    help="segundos extras de espera depois de esvaziar (retries/DLQ)")
    args = ap.parse_args()

    s = comum.sessao()
    sqs = s.client("sqs")
    principais = {k: comum.url_fila(comum.FILAS_PRINCIPAIS[k], s) for k in args.filas}
    dlqs = {k: comum.url_fila(v, s) for k, v in comum.DLQS.items()}

    t0 = time.time()
    vazias_seguidas = 0
    while True:
        decorrido = int(time.time() - t0)
        partes, total = [], 0
        for k, u in principais.items():
            vis, inv, dly = ler(sqs, u)
            total += vis + inv + dly
            partes.append(f"{k}: {vis} visíveis/{inv} em voo")
        dl = [f"{k}={ler(sqs, u)[0]}" for k, u in dlqs.items()]
        print(f"[{comum.agora_iso()} +{decorrido:4d}s] " + " | ".join(partes) + "  || DLQs: " + " ".join(dl), flush=True)

        vazias_seguidas = vazias_seguidas + 1 if total == 0 else 0
        if vazias_seguidas >= 2:
            print(f"Filas principais vazias após {decorrido}s.")
            break
        if decorrido >= args.timeout:
            print(f"TIMEOUT após {decorrido}s com {total} mensagens ainda nas filas.")
            sys.exit(2)
        time.sleep(args.intervalo)

    if args.depois:
        print(f"Aguardando mais {args.depois}s (retries/DLQ)...", flush=True)
        fim = time.time() + args.depois
        while time.time() < fim:
            time.sleep(min(60, max(0, fim - time.time())))
            dl = [f"{k}={ler(sqs, u)[0]}" for k, u in dlqs.items()]
            pr = [f"{k}={sum(ler(sqs, u))}" for k, u in principais.items()]
            print(f"[{comum.agora_iso()}] principais: {' '.join(pr)} || DLQs: {' '.join(dl)}", flush=True)


if __name__ == "__main__":
    main()
