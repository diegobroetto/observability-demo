"""
consultar_pedido/handler.py — GET /pedidos/{pedido_id}

Demonstra:
  - Cache hit/miss como métrica customizada via EMF
  - Subsegmento X-Ray isolado para a leitura no DynamoDB
  - Correlation ID propagado automaticamente pelo Powertools
  - Resposta 404 tratada como warning (não como erro de infraestrutura)
"""

import json
import os

import boto3
from botocore.exceptions import ClientError
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

dynamodb   = boto3.resource("dynamodb")
TABLE_NAME = os.environ["TABLE_NAME"]
table      = dynamodb.Table(TABLE_NAME)


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    try:
        pedido_id = event.get("pathParameters", {}).get("pedido_id")
        if not pedido_id:
            return _resposta(400, {"erro": "pedido_id é obrigatório"})

        # Adiciona pedido_id ao contexto de log — aparece em todos os logs desta invocação
        logger.append_keys(pedido_id=pedido_id)

        pedido = _buscar_pedido(pedido_id)

        if pedido is None:
            logger.warning("Pedido não encontrado", pedido_id=pedido_id)
            metrics.add_metric(name="PedidoNaoEncontrado", unit=MetricUnit.Count, value=1)
            return _resposta(404, {"erro": f"Pedido {pedido_id} não encontrado"})

        logger.info("Pedido consultado", status=pedido["status"])
        metrics.add_metric(name="PedidoConsultado", unit=MetricUnit.Count, value=1)

        return _resposta(200, pedido)

    except Exception as e:
        registrar_erro("consultar_pedido", e, pedido_id=pedido_id)
        return _resposta(500, {"erro": "Erro interno. Tente novamente."})


@tracer.capture_method
def _buscar_pedido(pedido_id: str) -> dict | None:
    """Busca o pedido no DynamoDB. Retorna None se não encontrado."""
    try:
        resposta = table.get_item(Key={"pedido_id": pedido_id})
        item = resposta.get("Item")

        # Anota no trace se foi um hit ou miss — visível no X-Ray
        tracer.put_annotation(key="cache_hit", value=item is not None)

        return item
    except ClientError as e:
        raise RuntimeError(f"Erro ao acessar DynamoDB: {e.response['Error']['Message']}") from e


def _resposta(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "application/json"},
        "body":       json.dumps(body, ensure_ascii=False, default=str),
    }
