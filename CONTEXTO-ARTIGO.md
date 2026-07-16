# Contexto para o artigo — observability-demo

> Este documento resume, em ordem cronológica, todos os problemas encontrados, causas raízes,
> correções aplicadas e decisões de arquitetura tomadas durante o desenvolvimento e operação
> deste projeto. Serve como material de apoio para quem for escrever o artigo
> *"Observabilidade serverless sem surpresa no bolso: logs, métricas e traces com CloudWatch + X-Ray do jeito certo"*.

## Visão geral do projeto

Aplicação serverless de pedidos (`observability-demo`) construída com AWS SAM, demonstrando:

- **Logs estruturados** via Powertools Logger (JSON nativo do Lambda)
- **Métricas customizadas** via Embedded Metric Format (EMF), sem custo extra de API
- **Traces distribuídos** via X-Ray + Powertools Tracer
- **Dashboard consolidado** no CloudWatch
- **Alarmes** em p99 de latência

Fluxo de negócio: `POST /pedidos` cria um pedido → publica evento no EventBridge →
`processar_pedido` (consumidor assíncrono) classifica automaticamente pelo valor:

| Valor | Status |
|---|---|
| ≤ R$ 500,00 | `aprovado` (automático) |
| R$ 500,01 – R$ 5.000,00 | `aguardando_aprovacao` (decisão manual via API) |
| > R$ 5.000,00 | `rejeitado` (automático) |

---

## 1. Erros de deploy iniciais e correções

### 1.1 CloudWatch Dashboard — validação falhando
**Erro:** widgets do dashboard rejeitados por falta da propriedade `region`.
**Causa:** todos os 6 widgets de métrica no `template.yaml` não declaravam `"region": "${AWS::Region}"`.
**Fix:** adicionada a propriedade `region` em todos os widgets do tipo `metric`.

### 1.2 SAM build falhando por incompatibilidade de arquitetura
**Erro:** `exec format error` / `JSONDecodeError` ao rodar `sam build --use-container`.
**Causa:** o ambiente de build (WSL2/Docker) é x86_64, mas o projeto usa `Architectures: [arm64]`
para as funções Lambda; a layer do Powertools não tinha a metadata de build explícita para arm64,
causando incompatibilidade binária ao instalar dependências nativas (ex: `cryptography`).
**Fix:**
- Instalada emulação QEMU/binfmt no Docker: `docker run --privileged --rm tonistiigi/binfmt --install all`
- Adicionado `BuildArchitecture: arm64` no `Metadata` da `PowertoolsLayer` em `template.yaml`

### 1.3 API Gateway Access Log Format rejeitado
**Erro:** CloudFormation rejeitando o `AccessLogSetting.Format`.
**Causa:** o formato estava definido como bloco YAML multi-linha (`>-`), mas a API Gateway espera
uma única string JSON válida.
**Fix:** reescrito como string JSON de uma linha só.

### 1.4 "Erro interno. Tente novamente." (500) mascarando causas reais
Investigação via CloudWatch Logs Insights revelou dois problemas distintos por trás do erro genérico:

**1.4.a — `TypeError: Float types are not supported. Use Decimal types instead.`**
DynamoDB não aceita `float` nativo do Python.
**Fix:** em `criar_pedido/handler.py`, o campo `valor` é convertido para
`Decimal(str(pedido["valor"]))` apenas no momento de persistir (o `dict` em memória continua
com `float` para logging/métricas/resposta HTTP).

**1.4.b — `AccessDeniedException` em `events:PutEvents`**
A função tentava publicar no event bus `default` por falta da variável de ambiente correta.
**Fix:** adicionado `EVENT_BUS_NAME: !Ref PedidosEventBus` em `Globals.Function.Environment.Variables`.

### 1.5 "Missing Authentication Token" nas novas rotas PATCH
Após deploy do `DecidirPedidoFunction`, chamadas às novas rotas retornavam 403.
**Causa real:** cache do CloudFront/API Gateway servindo uma resposta antiga de antes das rotas
existirem. Testar com um `pedido_id` novo (URL nunca antes acessada) confirmou que as rotas
estavam corretas e funcionando — não era um problema de configuração.

---

## 2. Nova funcionalidade: decisão manual de pedidos

### Motivação
Pedidos de valor médio (R$500,01–R$5.000,00) precisam de aprovação humana antes de seguir.
Foi criada uma única função Lambda (`DecidirPedidoFunction`) para tratar tanto aprovação quanto
rejeição — decisão de arquitetura para minimizar cold starts e custo (uma função a mais em vez de duas).

### Endpoints
| Método | Path | Descrição |
|---|---|---|
| PATCH | `/pedidos/{id}/aprovar` | Aprova um pedido em `aguardando_aprovacao` |
| PATCH | `/pedidos/{id}/rejeitar` | Rejeita um pedido em `aguardando_aprovacao` |

### Proteção de concorrência
A transição de estado usa `ConditionExpression` no DynamoDB
(`attribute_exists(pedido_id) AND #s = :esperado`), garantindo que:
- Decisões duplicadas ou pedidos já decididos retornam `409 Conflict` em vez de corromper o estado.
- Pedidos inexistentes retornam `404 Not Found`.

### Observabilidade da nova feature
- Métrica EMF `PedidoDecididoManualmente` com dimensão `Decisao` (aprovado/rejeitado).
- Anotação X-Ray `decisao_manual`.
- Log estruturado com `pedido_id`, `acao` e `novo_status`.
- Dashboard atualizado com o widget "Decisões Manuais — Aprovar/Rejeitar (EMF)".

---

## 3. Investigação: X-Ray sem dados (Service Map vazio)

Esse foi o troubleshooting mais complexo da sessão. O usuário reportou não conseguir ver o
Service Map / Application Map no X-Ray mesmo após gerar bastante tráfego de teste.

### Causa raiz 1 — Instrumentação OpenTelemetry (ADOT) fora do IaC
As 4 funções Lambda tinham, fora do `template.yaml`:
- Layer `AWSOpenTelemetryDistroPython` (ADOT)
- Variável de ambiente `AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument`
- Policy IAM `CloudWatchLambdaApplicationSignalsExecutionRolePolicy` anexada à role

Isso havia sido adicionado fora de banda (provavelmente via botão "Application Signals" no
console do Lambda), sobrescrevendo o mecanismo nativo do X-Ray usado pelo Powertools Tracer.
Resultado: os segmentos eram enviados via UDP normalmente pelo `aws_xray_sdk`, mas nunca
chegavam ao backend do X-Ray (`get-trace-summaries` retornava 0 traces processados).

**Fix:** removida a layer ADOT e a variável de ambiente das 4 funções; desanexada a policy
`CloudWatchLambdaApplicationSignalsExecutionRolePolicy` das roles via
`aws lambda update-function-configuration` + `aws iam detach-role-policy`.

### Causa raiz 2 — "Transaction Search" mal configurado na conta
Mesmo após o fix acima, `PutTraceSegments` continuava falhando com:
`"No segments could be converted to log events for account"`.

Investigação revelou que a conta tinha o destino de traces do X-Ray configurado para
`CloudWatchLogs` (feature "Transaction Search", que unifica X-Ray com Application Signals),
mas faltava a política de recursos do CloudWatch Logs que permite ao X-Ray escrever no
log group reservado `aws/spans`. Esse log group tem o prefixo reservado `aws/` e só pode ser
provisionado pelo próprio serviço da AWS via o fluxo oficial de habilitação.

**Fix definitivo:** como este projeto foi desenhado para X-Ray clássico (não Application Signals),
o destino dos traces foi revertido com:
```bash
aws xray update-trace-segment-destination --destination XRay
```
Isso restaurou imediatamente o armazenamento clássico de traces, sem depender do log group
reservado. Confirmado via `get-trace-summaries`: traces completos aparecendo com toda a
topologia esperada (`pedidos-criar-dev` → DynamoDB → EventBridge → `pedidos-processar-dev`).

**Lição para o artigo:** ao usar X-Ray clássico + Powertools Tracer, é importante garantir que
nenhuma automação de "Application Signals"/ADOT tenha sido habilitada nas mesmas funções, pois
os dois mecanismos de instrumentação competem e podem quebrar silenciosamente um ao outro sem
erro visível na aplicação (as chamadas UDP locais sempre "parecem" ter funcionado, já que UDP
não retorna erro de entrega).

---

## 4. Dashboard EMF com "No data available"

Três widgets do dashboard (`Cold Starts`, `Pedidos Processados por Status`, `Decisões Manuais`)
mostravam "No data available" mesmo com tráfego real sendo gerado.

**Causa raiz:** o Powertools Metrics sempre adiciona a dimensão `service=observability-demo`
em toda métrica emitida via EMF, além das dimensões de negócio (`Status`, `Decisao`,
`function_name`). No CloudWatch, uma métrica só corresponde a uma consulta se o **conjunto
exato de dimensões** for informado — os widgets pediam só a dimensão de negócio, sem `service`,
então nunca encontravam a métrica real (que tinha `service` + a dimensão de negócio).

**Fix:** adicionada a dimensão `"service", "observability-demo"` em todas as séries dos 3
widgets afetados no `template.yaml`. Validado via `aws cloudwatch get-metric-statistics` e
`get-metric-widget-image` que os dados passaram a aparecer corretamente.

**Nota de UX do CloudWatch console:** widgets de dashboard não re-buscam a *definição* das
métricas a cada auto-refresh — apenas os dados. Se a aba do navegador já estava aberta antes
de um deploy que altera a definição dos widgets, é necessário um hard refresh
(`Ctrl+Shift+R`) ou reabrir a aba para que a nova definição seja carregada.

---

## 5. Geração de tráfego de teste

Para popular métricas, traces e o dashboard, foram gerados múltiplos lotes de pedidos via
`curl` diretamente contra a API em produção, cobrindo:
- Pedidos de baixo valor (aprovação automática)
- Pedidos de valor médio (ficam `aguardando_aprovacao`, decididos manualmente em seguida —
  mistura de aprovações e rejeições)
- Pedidos de alto valor (rejeição automática)
- Casos de erro: payload inválido, JSON malformado, pedido inexistente, decisão em pedido já
  decidido (409), método HTTP não suportado (403)

No total, mais de 40 pedidos foram criados ao longo da sessão de testes, com dezenas de
decisões manuais aplicadas, gerando volume suficiente para validar todos os painéis do
dashboard e a presença de dados no X-Ray.

---

## Resumo de lições para o artigo

1. **Erros genéricos de 500 escondem causas específicas** — sempre correlacionar com
   CloudWatch Logs Insights antes de assumir que é um problema de infraestrutura.
2. **Cross-arch build (arm64) requer emulação explícita** no ambiente de desenvolvimento e
   metadata explícita no SAM template para cada layer.
3. **Instrumentação automática (Application Signals/ADOT) pode conflitar silenciosamente**
   com instrumentação manual (Powertools Tracer) — vale sempre auditar `Layers` e
   `AWS_LAMBDA_EXEC_WRAPPER` das funções quando o X-Ray "não mostra nada".
4. **Dimensões de métricas EMF precisam de correspondência exata** — bibliotecas como o
   Powertools adicionam dimensões automáticas (`service`) que precisam ser replicadas nas
   queries dos dashboards.
5. **CloudWatch dashboards cacheiam a definição dos widgets no navegador** — mudanças na
   estrutura exigem reload completo da página, não só o refresh automático dos dados.
