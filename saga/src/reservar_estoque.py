import os

import boto3
from botocore.exceptions import ClientError

from erros import EstoqueInsuficiente, ServicoIndisponivel

_dynamo = boto3.client("dynamodb")

ESTOQUE_TABLE = os.environ["ESTOQUE_TABLE"]
RESERVAS_TABLE = os.environ["RESERVAS_TABLE"]

_TRANSITORIOS = {"TransactionConflict", "ThrottlingError", "ProvisionedThroughputExceeded"}


def handler(event, _context):
    pedido_id = event["pedidoId"]
    produto_id = event["produtoId"]
    quantidade = int(event["quantidade"])

    try:
        _dynamo.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": ESTOQUE_TABLE,
                        "Key": {"produtoId": {"S": produto_id}},
                        "UpdateExpression": "SET disponivel = disponivel - :q",
                        "ConditionExpression": "disponivel >= :q",
                        "ExpressionAttributeValues": {":q": {"N": str(quantidade)}},
                    }
                },
                {
                    "Put": {
                        "TableName": RESERVAS_TABLE,
                        "Item": {
                            "pedidoId": {"S": pedido_id},
                            "produtoId": {"S": produto_id},
                            "quantidade": {"N": str(quantidade)},
                            "status": {"S": "RESERVADA"},
                        },
                        "ConditionExpression": "attribute_not_exists(pedidoId)",
                    }
                },
            ]
        )
    except ClientError as erro:
        if erro.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        codigos = [r.get("Code") for r in erro.response.get("CancellationReasons", [])]
        # A reserva deste pedido já existe: uma tentativa anterior chegou ao fim.
        if len(codigos) > 1 and codigos[1] == "ConditionalCheckFailed":
            return {"pedidoId": pedido_id, "reservado": True, "repetida": True}
        if codigos and codigos[0] == "ConditionalCheckFailed":
            raise EstoqueInsuficiente(f"Sem estoque de {produto_id} para {quantidade} unidade(s)")
        if any(c in _TRANSITORIOS for c in codigos):
            raise ServicoIndisponivel("DynamoDB com conflito ou throttling, tente de novo")
        raise

    return {"pedidoId": pedido_id, "reservado": True, "repetida": False}
