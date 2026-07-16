"""
criar_pedido/handler.py - POST /pedidos

Demonstra:
  - Logger com inject_lambda_context (cold_start, correlation ID)
  - Tracer com capture_lambda_handler e subsegmentos por operação
  - Metrics via EMF (sem put_metric_data)
  - Log level diferenciado por operação (info no caminho feliz, error no erro)
  - Sem log do evento completo em prod (LOG_EVENT=false)
"""

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

dynamodb    = boto3.resource("dynamodb")
eventbridge = boto3.client("events")

TABLE_NAME    = os.environ["TABLE_NAME"]
table         = dynamodb.Table(TABLE_NAME)
EVENT_BUS     = os.environ.get("EVENT_BUS_NAME", "default")


# ---------------------------------------------------------------------------
# Handler principal
#
# @logger.inject_lambda_context
#   Injeta: cold_start, function_name, function_arn, request_id
#   log_event=os.environ.get("LOG_EVENT") == "true"
#     → True em dev: loga o payload completo (útil para debug)
#     → False em prod: evita dados sensíveis no log e custo de ingestão
#
# @tracer.capture_lambda_handler
#   Cria automaticamente o segmento raiz no X-Ray com:
#     - Status code da resposta
#     - Exceções não tratadas
#     - Anotações de cold_start e service
#
# @metrics.log_metrics
#   Garante que todas as métricas EMF são emitidas ao final da invocação,
#   mesmo em caso de erro. capture_cold_start_metric=True emite uma
#   métrica ColdStart automaticamente.
# ---------------------------------------------------------------------------
@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    try:
        body = _parse_body(event)
        pedido = _montar_pedido(body)

        _salvar_pedido(pedido)
        _publicar_evento(pedido)

        metrics.add_metric(name="PedidoCriado", unit=MetricUnit.Count, value=1)

        logger.info("Pedido criado com sucesso", pedido_id=pedido["pedido_id"], valor=pedido["valor"])

        return _resposta(201, {"pedido_id": pedido["pedido_id"], "status": pedido["status"]})

    except ValueError as e:
        logger.warning("Payload inválido", erro=str(e))
        return _resposta(400, {"erro": str(e)})

    except Exception as e:
        registrar_erro("criar_pedido", e)
        return _resposta(500, {"erro": "Erro interno. Tente novamente."})


# ---------------------------------------------------------------------------
# Funções internas - cada uma com seu subsegmento no X-Ray
# ---------------------------------------------------------------------------

@tracer.capture_method
def _parse_body(event: dict) -> dict:
    """Valida e desserializa o body da requisição."""
    raw = event.get("body", "{}")
    try:
        body = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        raise ValueError("Body não é um JSON válido")

    campos_obrigatorios = ["produtos", "valor", "cliente_id"]
    faltando = [c for c in campos_obrigatorios if c not in body]
    if faltando:
        raise ValueError(f"Campos obrigatórios ausentes: {faltando}")

    if not isinstance(body["valor"], (int, float)) or body["valor"] <= 0:
        raise ValueError("Campo 'valor' deve ser um número positivo")

    return body


@tracer.capture_method
def _montar_pedido(body: dict) -> dict:
    """Monta a estrutura do pedido com ID e timestamps."""
    agora = datetime.now(timezone.utc).isoformat()
    return {
        "pedido_id":  str(uuid.uuid4()),
        "cliente_id": body["cliente_id"],
        "produtos":   body["produtos"],
        "valor":      body["valor"],
        "status":     "pendente",
        "criado_em":  agora,
        "atualizado_em": agora,
    }


@tracer.capture_method
def _salvar_pedido(pedido: dict) -> None:
    """Persiste o pedido no DynamoDB."""
    # DynamoDB não aceita float nativo - precisa de Decimal.
    # Convertido aqui (via str) só para o item persistido; o dict `pedido`
    # continua com float para logging/métricas/resposta HTTP.
    item = {**pedido, "valor": Decimal(str(pedido["valor"]))}

    # O X-Ray mostra automaticamente: tempo de chamada, tabela, operação
    table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(pedido_id)",  # idempotência
    )
    logger.debug("Pedido salvo no DynamoDB", pedido_id=pedido["pedido_id"])


@tracer.capture_method
def _publicar_evento(pedido: dict) -> None:
    """Publica evento PedidoCriado no EventBridge."""
    eventbridge.put_events(
        Entries=[{
            "Source":       "observability-demo.pedidos",
            "DetailType":   "PedidoCriado",
            "EventBusName": EVENT_BUS,
            "Detail":       json.dumps({
                "pedido_id":  pedido["pedido_id"],
                "cliente_id": pedido["cliente_id"],
                "valor":      pedido["valor"],
            }),
        }]
    )
    logger.debug("Evento PedidoCriado publicado", pedido_id=pedido["pedido_id"])


def _resposta(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "application/json"},
        "body":       json.dumps(body, ensure_ascii=False),
    }
