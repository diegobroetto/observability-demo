#!/usr/bin/env python3
"""gerar_pedidos.py — dispara N POST /pedidos contra a API deployada.

Os valores são distribuídos em rodízio nas três faixas do processar_pedido:
  - até R$ 500,00              (aprovado automaticamente)
  - de R$ 500,01 a R$ 5.000,00 (aguardando aprovação)
  - acima de R$ 5.000,00       (rejeitado)

Grava os pedido_id criados em scripts/saida/pedidos-<cenario>.txt, com um
cabeçalho (linhas "# chave=valor") que os outros scripts usam para saber a
janela de tempo do cenário.

Uso:
  python3 scripts/gerar_pedidos.py --quantidade 10
  python3 scripts/gerar_pedidos.py --quantidade 200 --concorrencia 20 --cenario com-flag
"""
import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import comum

FAIXAS = [
    ("ate-500", 10.00, 500.00),
    ("500-5000", 500.01, 5000.00),
    ("acima-5000", 5000.01, 20000.00),
]
PRODUTOS = ["prod-a", "prod-b", "prod-c", "prod-d", "prod-e"]


def montar_pedido(i, valor_texto):
    nome_faixa, vmin, vmax = FAIXAS[i % len(FAIXAS)]
    valor = round(random.uniform(vmin, vmax), 2)
    produtos = [
        {"id": p, "nome": f"Produto {p[-1].upper()}", "qty": random.randint(1, 3)}
        for p in random.sample(PRODUTOS, random.randint(1, 2))
    ]
    corpo = {
        "cliente_id": f"cli-{random.randint(1, 50):03d}",
        "produtos": produtos,
        # Número JSON com centavos, como um cliente real mandaria.
        "valor": f"{valor:.2f}" if valor_texto else valor,
    }
    return nome_faixa, corpo


def post(url, corpo, tentativas=3):
    dados = json.dumps(corpo).encode()
    for t in range(tentativas):
        req = urllib.request.Request(url, data=dados, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            corpo_erro = e.read().decode(errors="replace")
            if e.code == 429 and t < tentativas - 1:
                time.sleep(1 + t)
                continue
            return e.code, corpo_erro
        except urllib.error.URLError as e:
            if t < tentativas - 1:
                time.sleep(1 + t)
                continue
            return 0, str(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quantidade", type=int, default=10)
    ap.add_argument("--concorrencia", type=int, default=5)
    ap.add_argument("--cenario", default="fanout")
    ap.add_argument("--valor-texto", action="store_true",
                    help="manda o valor como texto (\"179.80\") em vez de número JSON")
    args = ap.parse_args()

    api = comum.outputs_stack()["ApiUrl"].rstrip("/")
    url = f"{api}/pedidos"
    print(f"API: {url}")
    print(f"Cenário: {args.cenario} | quantidade: {args.quantidade} | concorrência: {args.concorrencia}")

    comum.DIR_SAIDA.mkdir(parents=True, exist_ok=True)
    arq = comum.DIR_SAIDA / f"pedidos-{args.cenario}.txt"
    inicio = time.time()

    criados, erros, por_faixa = [], [], Counter()
    with ThreadPoolExecutor(max_workers=args.concorrencia) as pool:
        futuros = {}
        for i in range(args.quantidade):
            faixa, corpo = montar_pedido(i, args.valor_texto)
            futuros[pool.submit(post, url, corpo)] = (faixa, corpo)
        for n, f in enumerate(as_completed(futuros), 1):
            faixa, corpo = futuros[f]
            status, resp = f.result()
            if status == 201 and isinstance(resp, dict) and resp.get("pedido_id"):
                criados.append((resp["pedido_id"], faixa, corpo["valor"]))
                por_faixa[faixa] += 1
            else:
                erros.append((status, resp))
            if n % max(1, args.quantidade // 10) == 0 or n == args.quantidade:
                print(f"  {n}/{args.quantidade} enviados | criados={len(criados)} erros={len(erros)}")

    fim = time.time()
    with arq.open("w") as fh:
        fh.write(f"# cenario={args.cenario}\n")
        fh.write(f"# inicio_epoch={int(inicio)}\n")
        fh.write(f"# fim_epoch={int(fim)}\n")
        fh.write(f"# inicio_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(inicio))}\n")
        fh.write(f"# criados={len(criados)} erros={len(erros)}\n")
        fh.write(f"# por_faixa={json.dumps(dict(por_faixa))}\n")
        for pid, faixa, valor in criados:
            fh.write(f"{pid}\n")
    with (comum.DIR_SAIDA / f"pedidos-{args.cenario}.detalhe.tsv").open("w") as fh:
        fh.write("pedido_id\tfaixa\tvalor\n")
        for pid, faixa, valor in criados:
            fh.write(f"{pid}\t{faixa}\t{valor}\n")

    print(f"\nCriados: {len(criados)} | erros: {len(erros)} | {fim - inicio:.1f}s")
    print(f"Por faixa: {dict(por_faixa)}")
    print(f"Arquivo: {arq}")
    for status, resp in erros[:5]:
        print(f"  ERRO {status}: {str(resp)[:200]}")
    sys.exit(1 if erros and not criados else 0)


if __name__ == "__main__":
    main()
