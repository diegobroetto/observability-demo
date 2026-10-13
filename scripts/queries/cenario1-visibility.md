# Cenário 1 — duplicidade por visibility timeout (EstoqueQueue com VisibilityTimeout 10)

Log group: `/aws/lambda/pedidos-estoque-consumer-dev`. Intervalo: do início do cenário até agora.

## 1. Pedidos baixados por mais de uma invocação (query do print)

```sql
fields pedido_id, function_request_id
| filter message = "Iniciando baixa de estoque"
| stats count_distinct(function_request_id) as invocacoes by pedido_id
| filter invocacoes > 1
| sort invocacoes desc
```

## 2. Totais da janela

```sql
filter message in ["Iniciando baixa de estoque", "Baixa de estoque concluída"]
| stats count(*) as logs, count_distinct(pedido_id) as pedidos_distintos by message
```

## 3. Linha do tempo de um pedido repetido (troque o UUID)

```sql
fields @timestamp, function_request_id, message, latencia_simulada_s
| filter pedido_id = "COLE-AQUI-O-PEDIDO-ID"
| sort @timestamp asc
```
