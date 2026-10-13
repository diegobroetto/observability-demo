"""decidir_pedido/handler.py — PATCH /pedidos/{id}/aprovar e /rejeitar"""
import json, os
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, context):
    pedido_id = event["pathParameters"]["pedido_id"]
    acao = "aprovado" if event["resource"].endswith("/aprovar") else "rejeitado"
    logger.append_keys(pedido_id=pedido_id, acao=acao)

    try:
        agora = datetime.now(timezone.utc).isoformat()
        table.update_item(
            Key={"pedido_id": pedido_id},
            UpdateExpression="SET #s = :novo, atualizado_em = :agora",
            ConditionExpression="attribute_exists(pedido_id) AND #s = :esperado",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":novo": acao, ":agora": agora, ":esperado": "aguardando_aprovacao",
            },
        )
        tracer.put_annotation(key="decisao_manual", value=acao)
        metrics.add_metric(name="PedidoDecididoManualmente", unit=MetricUnit.Count, value=1)
        metrics.add_dimension(name="Decisao", value=acao)
        logger.info("Decisão manual aplicada", novo_status=acao)
        return _resposta(200, {"pedido_id": pedido_id, "status": acao})

    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            item = table.get_item(Key={"pedido_id": pedido_id}).get("Item")
            if item is None:
                return _resposta(404, {"erro": "Pedido não encontrado"})
            return _resposta(409, {"erro": f"Pedido está em status '{item['status']}', não em aguardando_aprovacao"})
        registrar_erro("decidir_pedido", e, pedido_id=pedido_id)
        return _resposta(500, {"erro": "Erro interno. Tente novamente."})


def _resposta(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False)}
