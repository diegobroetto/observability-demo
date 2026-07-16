# observability-demo

Exemplo completo de observabilidade serverless com **CloudWatch + X-Ray** para o artigo:

> *"Observabilidade serverless sem surpresa no bolso: logs, métricas e traces com CloudWatch + X-Ray do jeito certo"*

---

## O que este projeto demonstra

| Pilar | Ferramenta | Onde ver no código |
|---|---|---|
| **Logs estruturados** | Powertools Logger + JSON nativo do Lambda | `observability.py`, todos os handlers |
| **Retenção de logs** | AWS::Logs::LogGroup com RetentionInDays | `template.yaml` → LogGroups |
| **Log level por ambiente** | Mappings no SAM + LOG_EVENT flag | `template.yaml` → Mappings |
| **Métricas sem custo extra** | Embedded Metric Format (EMF) | `criar_pedido/handler.py` |
| **Métricas com dimensão de negócio** | Powertools Metrics + add_dimension | `processar_pedido/handler.py` |
| **Traces por subsegmento** | Powertools Tracer + @capture_method | Todos os handlers |
| **Anotações no X-Ray** | tracer.put_annotation | `consultar_pedido/handler.py` |
| **Alarmes em p99** | AWS::CloudWatch::Alarm + ExtendedStatistic | `template.yaml` → Alarmes |
| **Dashboard consolidado** | AWS::CloudWatch::Dashboard | `template.yaml` → Dashboard |
| **Queries prontas** | CloudWatch Logs Insights | `monitoring/insights-queries.md` |

---

## Endpoints

| Método | Path | Função | Descrição |
|---|---|---|---|
| POST | `/pedidos` | CriarPedidoFunction | Cria o pedido e publica `PedidoCriado` no EventBridge |
| GET | `/pedidos/{id}` | ConsultarPedidoFunction | Consulta o pedido por ID |
| PATCH | `/pedidos/{id}/aprovar` | DecidirPedidoFunction | Aprova manualmente um pedido em `aguardando_aprovacao` |
| PATCH | `/pedidos/{id}/rejeitar` | DecidirPedidoFunction | Rejeita manualmente um pedido em `aguardando_aprovacao` |

O `processar_pedido` (consumidor assíncrono do EventBridge) classifica automaticamente
pelo valor do pedido:

| Valor | Status |
|---|---|
| ≤ R$ 500,00 | `aprovado` (automático) |
| R$ 500,01 – R$ 5.000,00 | `aguardando_aprovacao` (precisa de decisão manual) |
| > R$ 5.000,00 | `rejeitado` (automático) |

Pedidos em `aguardando_aprovacao` só saem desse estado via `/aprovar` ou `/rejeitar`.
A transição é protegida por `ConditionExpression` no DynamoDB - chamadas concorrentes
ou fora de ordem retornam `409 Conflict` em vez de corromper o estado.

```bash
# Aprovar
curl -X PATCH https://SEU-ID.execute-api.SUA-REGIAO.amazonaws.com/dev/pedidos/PEDIDO_ID/aprovar

# Rejeitar
curl -X PATCH https://SEU-ID.execute-api.SUA-REGIAO.amazonaws.com/dev/pedidos/PEDIDO_ID/rejeitar
```

---

## Estrutura

```
observability-demo/
├── template.yaml                    # SAM - toda a infra
├── samconfig.toml                   # Deploy por ambiente
├── layers/
│   └── powertools/
│       └── requirements.txt         # aws-lambda-powertools
├── src/
│   ├── criar_pedido/
│   │   ├── handler.py               # POST /pedidos
│   │   ├── observability.py         # Logger, Tracer, Metrics centralizados
│   │   └── requirements.txt
│   ├── consultar_pedido/
│   │   ├── handler.py               # GET /pedidos/{id}
│   │   ├── observability.py
│   │   └── requirements.txt
│   ├── decidir_pedido/
│   │   ├── handler.py               # PATCH /pedidos/{id}/aprovar e /rejeitar
│   │   ├── observability.py
│   │   └── requirements.txt
│   └── processar_pedido/
│       ├── handler.py               # Consumidor EventBridge
│       ├── observability.py
│       └── requirements.txt
├── events/
│   ├── criar_pedido_valido.json
│   ├── criar_pedido_alto_valor.json
│   └── processar_pedido.json
└── monitoring/
    └── insights-queries.md          # Queries prontas para Logs Insights
```

---

## Pré-requisitos

- AWS CLI configurado (`aws configure`)
- SAM CLI (`brew install aws-sam-cli`)
- Docker em execução (para `sam build --use-container`)
- Python 3.13

---

## Deploy

```bash
# Build - compila para Amazon Linux 2023 / arm64
sam build --use-container

# Primeiro deploy (configura S3 bucket, pergunta região etc.)
sam deploy --guided

# Deploys seguintes por ambiente
sam deploy --config-env dev
sam deploy --config-env staging
sam deploy --config-env prod
```

---

## Teste local

```bash
# POST /pedidos - pedido válido (aprovação automática)
sam local invoke CriarPedidoFunction \
  --event events/criar_pedido_valido.json \
  --env-vars env.json

# POST /pedidos - pedido de alto valor (aprovação manual)
sam local invoke CriarPedidoFunction \
  --event events/criar_pedido_alto_valor.json

# Processamento assíncrono via EventBridge
sam local invoke ProcessarPedidoFunction \
  --event events/processar_pedido.json
```

> **Nota:** o teste local não persiste no DynamoDB real nem emite traces para o X-Ray.
> Para testar o fluxo completo, use `sam deploy --config-env dev` e invoque via API.

---

## O que observar depois do deploy

### Logs
1. CloudWatch → Log groups → `/aws/lambda/pedidos-criar-dev`
2. Observe o formato JSON com `cold_start`, `function_name`, `pedido_id`
3. Rode as queries em `monitoring/insights-queries.md` no Logs Insights

### Métricas
1. CloudWatch → Metrics → `observability-demo/Pedidos`
2. Veja as métricas EMF: `PedidoCriado`, `PedidoProcessado`, `ColdStart`
3. Filtre `PedidoProcessado` pela dimensão `Status`

### Traces
1. CloudWatch → X-Ray → Traces
2. Filtre por `service("pedidos-criar-dev")`
3. Clique em um trace e veja os subsegmentos: `_parse_body`, `_salvar_pedido`, `_publicar_evento`
4. Veja a anotação `status_pedido` nos traces da função processar

### Dashboard
```
# URL gerada pelo stack - disponível nos Outputs do CloudFormation
aws cloudformation describe-stacks \
  --stack-name observability-demo-dev \
  --query "Stacks[0].Outputs[?OutputKey=='DashboardUrl'].OutputValue" \
  --output text
```

---

## Configurações por ambiente

| Config | dev | staging | prod |
|---|---|---|---|
| Log level | DEBUG | INFO | INFO |
| Log do evento | ✅ sim | ❌ não | ❌ não |
| X-Ray sampling | 100% | 20% | 5% |
| Retenção logs | 7 dias | 30 dias | 90 dias |
| DynamoDB PITR | ❌ | ❌ | ✅ |

---

## Limpeza

```bash
sam delete --stack-name observability-demo-dev
```

---

## Artigo completo

[Dev.to - Série Serverless na Prática](https://dev.to/diegobroetto)
