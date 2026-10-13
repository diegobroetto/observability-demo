# Cenário 2 — resposta parcial de lote com e sem ReportBatchItemFailures

Log group: `/aws/lambda/pedidos-notificacao-consumer-dev`. Intervalo: do início da rodada até agora.
A linha "Falha simulada no envio" é a adicionada no handler para rastrear cada falha.

## 1. Falhas e envios por pedido (base da classificação)

```sql
filter message in ["Falha simulada no envio", "Notificação enviada ao cliente"]
| stats count(*) as n by pedido_id, message
| limit 10000
```

## 2. Pedidos que falharam e nunca foram enviados (candidatos a "sumiram")

O script cruza este resultado com a NotificacaoDLQ; o que não estiver lá sumiu.

```sql
filter message in ["Falha simulada no envio", "Notificação enviada ao cliente"]
| stats sum(message = "Falha simulada no envio") as falhas,
        sum(message = "Notificação enviada ao cliente") as envios by pedido_id
| filter falhas > 0 and envios = 0
| limit 10000
```

## 3. Lotes: tamanho médio e lotes com falha parcial

```sql
filter message = "Lote com falhas parciais"
| stats count(*) as lotes_com_falha, avg(total) as tamanho_medio_lote,
        sum(falhas) as itens_falhos, max(total) as maior_lote
```
