"""criar_pedido/handler.py — POST /pedidos"""
import json, os, uuid
from datetime import datetime, timezone
from decimal import Decimal
import boto3
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit

dynamodb    = boto3.resource("dynamodb")
eventbridge = boto3.client("events")
table       = dynamodb.Table(os.environ["TABLE_NAME"])
EVENT_BUS   = os.environ["EVENT_BUS_NAME"]


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        pedido_id = str(uuid.uuid4())
        agora = datetime.now(timezone.utc).isoformat()
        pedido = {
            "pedido_id": pedido_id,
            "cliente_id": body["cliente_id"],
            "produtos": body["produtos"],
            "valor": body["valor"],
            "status": "pendente",
            "criado_em": agora,
            "atualizado_em": agora,
        }

        # DynamoDB não aceita float nativo: o valor vai como Decimal só no item
        # gravado; o evento publicado continua com o número do JSON.
        item = {**pedido, "valor": Decimal(str(pedido["valor"]))}
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pedido_id)")

        eventbridge.put_events(Entries=[{
            "Source":       "observability-demo.pedidos",
            "DetailType":   "PedidoCriado",
            "EventBusName": EVENT_BUS,
            "Detail":       json.dumps({
                "pedido_id":  pedido_id,
                "cliente_id": pedido["cliente_id"],
                "valor":      pedido["valor"],
                "produtos":   pedido["produtos"],
            }),
        }])

        metrics.add_metric(name="PedidoCriado", unit=MetricUnit.Count, value=1)
        logger.info("Pedido criado", pedido_id=pedido_id, valor=pedido["valor"])

        return _resposta(201, {"pedido_id": pedido_id, "status": "pendente"})

    except Exception as e:
        registrar_erro("criar_pedido", e)
        return _resposta(500, {"erro": "Erro interno. Tente novamente."})


def _resposta(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False)}
