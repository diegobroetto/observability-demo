"""
processar_pedido/handler.py — consumidor EventBridge (assíncrono)

Demonstra:
  - Métricas com dimensões de negócio (Status do pedido)
  - Tratamento de idempotência com log de alerta (não erro)
  - Anotações no X-Ray para filtrar traces por resultado
  - SQS Dead Letter Queue implícita via EventBridge (retry automático)
  - Duração do processamento como métrica customizada
"""

import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

dynamodb   = boto3.resource("dynamodb")
TABLE_NAME = os.environ["TABLE_NAME"]
table      = dynamodb.Table(TABLE_NAME)

LIMITE_APROVACAO_AUTOMATICA = Decimal("500.00")


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: dict, context: LambdaContext) -> None:
    inicio = time.perf_counter()

    # O evento vem do EventBridge — extrai o detail
    detail = event.get("detail", {})
    pedido_id  = detail.get("pedido_id")
    valor      = Decimal(str(detail.get("valor", 0)))

    logger.append_keys(pedido_id=pedido_id, valor=float(valor))

    try:
        status = _definir_status(valor)
        tracer.put_annotation(key="status_pedido", value=status)

        _atualizar_status(pedido_id, status)

        duracao_ms = (time.perf_counter() - inicio) * 1000

        # Métrica com dimensão de negócio — cardinalidade baixa (aprovado/rejeitado/manual)
        metrics.add_metric(name="PedidoProcessado", unit=MetricUnit.Count, value=1)
        metrics.add_dimension(name="Status", value=status)

        # Duração do processamento — útil para detectar degradação
        metrics.add_metric(name="DuracaoProcessamento", unit=MetricUnit.Milliseconds, value=duracao_ms)

        logger.info(
            "Pedido processado",
            status=status,
            duracao_ms=round(duracao_ms, 2),
        )

    except Exception as e:
        registrar_erro("processar_pedido", e, pedido_id=pedido_id)
        # Re-raise para o EventBridge fazer retry (até o limite configurado)
        raise


def _definir_status(valor: Decimal) -> str:
    """Regra de negócio: pedidos acima do limite vão para aprovação manual."""
    if valor <= LIMITE_APROVACAO_AUTOMATICA:
        return "aprovado"
    elif valor <= Decimal("5000.00"):
        return "aguardando_aprovacao"
    else:
        return "rejeitado"


@tracer.capture_method
def _atualizar_status(pedido_id: str, status: str) -> None:
    """Atualiza o status do pedido no DynamoDB com proteção de idempotência."""
    agora = datetime.now(timezone.utc).isoformat()

    try:
        table.update_item(
            Key={"pedido_id": pedido_id},
            UpdateExpression="SET #s = :status, atualizado_em = :agora",
            # Só atualiza se o pedido ainda está pendente — idempotência
            ConditionExpression="#s = :pendente",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status":   status,
                ":agora":    agora,
                ":pendente": "pendente",
            },
        )
        logger.debug("Status atualizado no DynamoDB", status=status)

    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Pedido já foi processado — idempotência garantida
            logger.warning(
                "Pedido já processado anteriormente — ignorando",
                pedido_id=pedido_id,
            )
            return
        raise
