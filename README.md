# observability-demo — Event-driven com EventBridge + SQS

Extensão do projeto `observability-demo` para o artigo:

> *"Event-driven com EventBridge + SQS: quando cada um entra e como evitar os erros mais comuns"*

---

## O cenário

Um único evento `PedidoCriado` é roteado (fan-out) para **3 filas SQS independentes** e para **1 Lambda como alvo direto, sem fila**, cada rota demonstrando uma lição diferente:

```
                                    ┌─→ EstoqueQueue      → estoque_consumer
                                    │   (visibility timeout correto)
EventBridge                        │
(PedidoCriado)  ──── fan-out ──────┼─→ NotificacaoQueue  → notificacao_consumer
                                    │   (ReportBatchItemFailures)
                                    │
                                    └─→ FinanceiroQueue    → financeiro_consumer
                                        (DLQ + erro permanente)

                    + regra direta → processar_pedido (Lambda, sem fila)
```

| Rota | Lição | Onde ver |
|---|---|---|
| `EstoqueQueue` | Visibility timeout precisa ser >= 6x o timeout da função; abaixo do tempo de processamento, a mensagem reaparece e é processada 2x | `src/estoque_consumer/handler.py` |
| `NotificacaoQueue` | `ReportBatchItemFailures` no event source mapping, junto com o `BatchProcessor`, para que só as mensagens que falharam voltem para a fila | `src/notificacao_consumer/handler.py` |
| `FinanceiroQueue` | DLQ configurada de ponta a ponta para erro permanente (não passageiro) + alarme na DLQ | `src/financeiro_consumer/handler.py` |
| Regra direta → `processar_pedido` | Quando o EventBridge sozinho basta. Exige duas redes: `DeadLetterConfig` na regra (falha de entrega) e destino `OnFailure` no Lambda (falha de processamento) | `template.yaml` → `ProcessarPedidoFunction` |

---

## Estrutura

```
observability-demo/
├── template.yaml                      # SAM — toda a infra, incluindo o fan-out
├── samconfig.toml
├── layers/powertools/requirements.txt
├── src/
│   ├── criar_pedido/                  # POST /pedidos — publica no EventBridge
│   ├── consultar_pedido/              # GET /pedidos/{id}
│   ├── decidir_pedido/                # PATCH .../aprovar e /rejeitar
│   ├── processar_pedido/              # alvo direto do EventBridge, sem fila (classificação)
│   ├── estoque_consumer/              # consumidor SQS — lição de visibility timeout
│   ├── notificacao_consumer/          # consumidor SQS — lição de batch item failures
│   └── financeiro_consumer/           # consumidor SQS — lição de DLQ
├── events/                            # payloads de teste
└── monitoring/insights-queries.md
```

---

## Deploy

```bash
sam build --use-container
sam deploy --config-env dev
```

---

## Reproduzindo os erros de propósito

### 1. Duplicidade por visibility timeout (EstoqueQueue)

No `template.yaml`, mude:

```yaml
EstoqueQueue:
  Properties:
    VisibilityTimeout: 180   # troque para 10
```

Redeploy, gere alguns pedidos via API, e observe nos logs do `estoque_consumer` o mesmo `pedido_id` sendo processado por invocações diferentes antes da primeira terminar. A métrica `EstoqueBaixado` vai contar mais que o número real de pedidos criados.

### 2. Falhas parciais sumindo sem a flag (NotificacaoQueue)

Remova `FunctionResponseTypes: [ReportBatchItemFailures]` do event source mapping da `NotificacaoConsumerFunction` no template e faça o redeploy. Gere um volume de pedidos suficiente para formar lotes de 10 mensagens. Com 25% de falha simulada, quase todo lote terá pelo menos uma falha.

O que observar: o handler termina sem erro (o `BatchProcessor` captura as falhas e devolve a lista `batchItemFailures`), e o Lambda apaga do SQS as mensagens de uma invocação bem-sucedida. Compare, no Logs Insights, os `pedido_id` com o log "Timeout simulado no provedor de notificação" com os que depois aparecem em "Notificação enviada ao cliente". Sem a flag, as mensagens que falharam não devem voltar para a fila nem chegar à `NotificacaoDLQ`.

Exceção: se todas as mensagens de um lote falharem, o `BatchProcessor` lança `BatchProcessingError`, a invocação falha e o lote inteiro volta para a fila.

### 3. DLQ pegando erro permanente (FinanceiroQueue)

Não precisa mudar nada — já está configurado certo. Gere pedidos e espere: ~10% vão cair em erro permanente simulado, o SQS vai tentar 3 vezes (`maxReceiveCount: 3`), e a mensagem vai parar na `FinanceiroDLQ`. O alarme `FinanceiroDLQAlarm` dispara assim que isso acontece.

---

## Testes locais

```bash
sam local invoke CriarPedidoFunction --event events/criar_pedido_valido.json
sam local invoke EstoqueConsumerFunction --event events/sqs_batch_estoque.json
```

> Testes locais não passam pelo EventBridge nem pelo roteamento real das regras — para ver o fan-out de verdade, é preciso deploy.

---

## Limpeza

```bash
sam delete --stack-name observability-demo-dev
```
