# CloudWatch Logs Insights — Queries prontas

Cole estas queries no console em: CloudWatch → Logs Insights
Selecione o log group da função desejada e ajuste o intervalo de tempo.

---

## 1. Taxa de erro por função nos últimos 60 minutos

```
filter level = "ERROR"
| stats count() as total_erros by bin(5m) as periodo
| sort periodo desc
```

---

## 2. Cold starts — frequência e funções mais afetadas

```
filter cold_start = true
| stats count() as cold_starts by function_name
| sort cold_starts desc
```

---

## 3. Pedidos com maior latência (p99) — últimas 3 horas

```
filter ispresent(pedido_id)
| stats
    count() as invocacoes,
    pct(@duration, 50) as p50_ms,
    pct(@duration, 95) as p95_ms,
    pct(@duration, 99) as p99_ms
  by function_name
| sort p99_ms desc
```

---

## 4. Erros agrupados por tipo — para priorizar o que corrigir

```
filter level = "ERROR"
| stats count() as ocorrencias by tipo_erro, operacao
| sort ocorrencias desc
| limit 20
```

---

## 5. Rastrear um pedido específico — toda a jornada

```
# Substitua o valor de pedido_id pelo ID real
filter pedido_id = "SEU-PEDIDO-ID-AQUI"
| fields @timestamp, level, mensagem, function_name, status
| sort @timestamp asc
```

---

## 6. Custo estimado de ingestão de logs por log group

```
# Rode no log group /aws/lambda/* ou selecione múltiplos grupos
stats sum(@ingestionTime) as bytes_ingeridos by @logStream
| stats sum(bytes_ingeridos) as total_bytes
```

---

## 7. Invocações sem cold start vs com cold start — proporção

```
stats
  sum(cold_start = true) as com_cold_start,
  sum(cold_start = false) as sem_cold_start,
  count() as total
| fields
  (com_cold_start / total * 100) as pct_cold_start
```

---

## 8. Pedidos por status nas últimas 24h

```
# Use no log group da função processar_pedido
filter mensagem = "Pedido processado"
| stats count() as total by status
| sort total desc
```

---

## Dica de custo

Queries no Logs Insights cobram por GB escaneado ($0.005/GB).
Para reduzir custo:
- Use filtros antes de stats — o `filter` reduz o volume processado
- Selecione o menor intervalo de tempo que responde sua pergunta
- Use log groups específicos, não o curinga /* quando possível
- Considere criar métricas via EMF para perguntas que você faz frequentemente
  (métrica = consulta gratuita, Insights = cobrado por GB)
