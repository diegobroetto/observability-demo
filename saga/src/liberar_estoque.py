import os

import boto3
from botocore.exceptions import ClientError

from erros import ServicoIndisponivel

_dynamo = boto3.client("dynamodb")

ESTOQUE_TABLE = os.environ["ESTOQUE_TABLE"]
RESERVAS_TABLE = os.environ["RESERVAS_TABLE"]


def handler(event, _context):
    """Compensação de ReservarEstoque. Idempotente: pode rodar duas vezes sem devolver estoque em dobro."""
    pedido_id = event["pedidoId"]
    produto_id = event["produtoId"]
    quantidade = int(event["quantidade"])

    try:
        _dynamo.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": RESERVAS_TABLE,
                        "Key": {"pedidoId": {"S": pedido_id}},
                        "UpdateExpression": "SET #s = :liberada",
                        "ConditionExpression": "#s = :reservada",
                        "ExpressionAttributeNames": {"#s": "status"},
                        "ExpressionAttributeValues": {
                            ":liberada": {"S": "LIBERADA"},
                            ":reservada": {"S": "RESERVADA"},
                        },
                    }
                },
                {
                    "Update": {
                        "TableName": ESTOQUE_TABLE,
                        "Key": {"produtoId": {"S": produto_id}},
                        "UpdateExpression": "SET disponivel = disponivel + :q",
                        "ExpressionAttributeValues": {":q": {"N": str(quantidade)}},
                    }
                },
            ]
        )
    except ClientError as erro:
        if erro.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        codigos = [r.get("Code") for r in erro.response.get("CancellationReasons", [])]
        if codigos and codigos[0] == "ConditionalCheckFailed":
            # Nada reservado ou já liberado: não há o que desfazer.
            return {"pedidoId": pedido_id, "liberado": False}
        raise ServicoIndisponivel("DynamoDB com conflito, tente de novo")

    return {"pedidoId": pedido_id, "liberado": True}
