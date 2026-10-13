"""consultar_pedido/handler.py — GET /pedidos/{pedido_id}"""
import json, os
import boto3
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, context):
    pedido_id = event["pathParameters"]["pedido_id"]
    logger.append_keys(pedido_id=pedido_id)
    try:
        item = table.get_item(Key={"pedido_id": pedido_id}).get("Item")
        if item is None:
            metrics.add_metric(name="PedidoNaoEncontrado", unit=MetricUnit.Count, value=1)
            return _resposta(404, {"erro": f"Pedido {pedido_id} não encontrado"})
        metrics.add_metric(name="PedidoConsultado", unit=MetricUnit.Count, value=1)
        return _resposta(200, item)
    except Exception as e:
        registrar_erro("consultar_pedido", e, pedido_id=pedido_id)
        return _resposta(500, {"erro": "Erro interno. Tente novamente."})


def _resposta(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}
