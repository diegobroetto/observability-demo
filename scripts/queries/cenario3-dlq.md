# Cenário 3 — DLQ e alarme (FinanceiroQueue)

O handler do financeiro não loga o erro permanente: a exceção sobe para o BatchProcessor,
que devolve o item em `batchItemFailures`. Por isso o retrato do cenário vem da DLQ e da
métrica, não dos logs da aplicação.

## 1. Cobranças geradas x pedidos do cenário (log group `/aws/lambda/pedidos-financeiro-consumer-dev`)

```sql
filter message = "Cobrança gerada"
| stats count(*) as cobrancas, count_distinct(pedido_id) as pedidos_distintos
```

## 2. Invocações com item falho (cada erro permanente aparece 3 vezes, uma por tentativa)

```sql
fields @timestamp, @message
| filter @message like /batchItemFailures/ or level = "ERROR"
| sort @timestamp asc
| limit 200
```

## Fora do Logs Insights

```bash
python3 scripts/analisar.py dlq --cenario dlq          # lê a DLQ sem apagar + estado do alarme
aws cloudwatch describe-alarms --alarm-names pedidos-financeiro-dlq-com-item-dev \
  --profile darede-sandbox --region us-east-1 \
  --query 'MetricAlarms[].{estado:StateValue,desde:StateUpdatedTimestamp,motivo:StateReason}'
```
