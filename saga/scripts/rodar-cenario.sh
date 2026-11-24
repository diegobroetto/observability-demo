#!/usr/bin/env bash
# Uso: scripts/rodar-cenario.sh <ok|sem-estoque|pagamento-recusado|gateway-instavel|confirmacao-falha|estorno-falha> [stack]
set -euo pipefail
CENARIO="${1:?informe o cenario}"
STACK="${2:-observability-demo-saga-dev}"
ARN=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='PedidoSagaArn'].OutputValue" --output text)
ID="teste-$(date +%s)"
INPUT=$(sed "s/\"pedidoId\": \"[^\"]*\"/\"pedidoId\": \"$ID\"/" "events/pedido-$CENARIO.json")
EXEC=$(aws stepfunctions start-execution --state-machine-arn "$ARN" --input "$INPUT" \
  --query executionArn --output text)
echo "Execucao: $EXEC"
for _ in $(seq 1 60); do
  STATUS=$(aws stepfunctions describe-execution --execution-arn "$EXEC" --query status --output text)
  [ "$STATUS" != "RUNNING" ] && break
  sleep 3
done
echo "Status: $STATUS"
aws stepfunctions get-execution-history --execution-arn "$EXEC" --reverse-order --max-items 1 \
  --query "events[0].type" --output text
