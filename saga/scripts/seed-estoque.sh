#!/usr/bin/env bash
# Uso: scripts/seed-estoque.sh [stack] [quantidade]
set -euo pipefail
STACK="${1:-observability-demo-saga-dev}"
QTD="${2:-10}"
TABELA=$(aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='EstoqueTableName'].OutputValue" --output text)
aws dynamodb put-item --table-name "$TABELA" \
  --item "{\"produtoId\":{\"S\":\"prod-camiseta\"},\"disponivel\":{\"N\":\"$QTD\"}}"
echo "Estoque de prod-camiseta = $QTD em $TABELA"
