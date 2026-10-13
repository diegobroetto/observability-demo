# Cenário 0 — fan-out funcionando

Rode a mesma query em cada um dos log groups abaixo, com o intervalo de tempo do cenário:
`/aws/lambda/pedidos-processar-dev`, `/aws/lambda/pedidos-estoque-consumer-dev`,
`/aws/lambda/pedidos-notificacao-consumer-dev`, `/aws/lambda/pedidos-financeiro-consumer-dev`.

## 1. O pedido chegou ao consumidor? (troque o UUID)

Como `LOG_EVENT=true` em dev, cada invocação loga o evento recebido inteiro, então o
`pedido_id` aparece no `@message` mesmo quando o processamento falha.

```sql
fields @timestamp, message, function_request_id
| filter @message like /COLE-AQUI-O-PEDIDO-ID/
| sort @timestamp asc
```

## 2. Resultado de negócio por pedido em cada consumidor

```sql
fields @timestamp, message, pedido_id
| filter message in ["Pedido processado", "Iniciando baixa de estoque", "Baixa de estoque concluída",
                     "Notificação enviada ao cliente", "Falha simulada no envio", "Cobrança gerada"]
| sort @timestamp asc
| limit 10000
```
