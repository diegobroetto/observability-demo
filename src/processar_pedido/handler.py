"""processar_pedido/handler.py — consumidor EventBridge: classifica pedido por valor."""
import os
from decimal import Decimal
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])

LIMITE_AUTOMATICO = Decimal("500.00")
LIMITE_MANUAL      = Decimal("5000.00")


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, context):
    detail = event.get("detail", {})
    pedido_id = detail.get("pedido_id")
    valor = Decimal(str(detail.get("valor", 0)))
    logger.append_keys(pedido_id=pedido_id, valor=float(valor))

    try:
        status = _definir_status(valor)
        tracer.put_annotation(key="status_pedido", value=status)
        _atualizar_status(pedido_id, status)

        metrics.add_metric(name="PedidoProcessado", unit=MetricUnit.Count, value=1)
        metrics.add_dimension(name="Status", value=status)
        logger.info("Pedido processado", status=status)
    except Exception as e:
        registrar_erro("processar_pedido", e, pedido_id=pedido_id)
        raise


def _definir_status(valor):
    if valor <= LIMITE_AUTOMATICO:
        return "aprovado"
    elif valor <= LIMITE_MANUAL:
        return "aguardando_aprovacao"
    return "rejeitado"


@tracer.capture_method
def _atualizar_status(pedido_id, status):
    agora = datetime.now(timezone.utc).isoformat()
    try:
        table.update_item(
            Key={"pedido_id": pedido_id},
            UpdateExpression="SET #s = :status, atualizado_em = :agora",
            ConditionExpression="#s = :pendente",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": status, ":agora": agora, ":pendente": "pendente"},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.warning("Pedido já processado — ignorando", pedido_id=pedido_id)
            return
        raise
