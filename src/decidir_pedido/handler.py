"""
decidir_pedido/handler.py — PATCH /pedidos/{pedido_id}/aprovar e /rejeitar

Demonstra:
  - Duas rotas de API mapeadas para o mesmo Lambda (menos cold start/custo
    do que duas funções quase idênticas)
  - Transição de estado protegida por ConditionExpression — evita corrida
    entre duas decisões concorrentes e detecta pedido inexistente
  - Métrica com dimensão de negócio para decisões manuais
  - 409 Conflict quando o pedido não está no estado esperado
"""

import json
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

dynamodb   = boto3.resource("dynamodb")
TABLE_NAME = os.environ["TABLE_NAME"]
table      = dynamodb.Table(TABLE_NAME)

STATUS_ELEGIVEL = "aguardando_aprovacao"
ACOES = {
    "aprovar":  "aprovado",
    "rejeitar": "rejeitado",
}


class _PedidoNaoEncontrado(Exception):
    pass


class _ConflitoDeEstado(Exception):
    """str(e) devolve o status atual do pedido, usado na mensagem de erro."""
    pass


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    pedido_id = (event.get("pathParameters") or {}).get("pedido_id")
    try:
        if not pedido_id:
            return _resposta(400, {"erro": "pedido_id é obrigatório"})

        acao = _extrair_acao(event)
        if acao is None:
            return _resposta(400, {"erro": "Ação inválida. Use /aprovar ou /rejeitar"})

        novo_status = ACOES[acao]
        logger.append_keys(pedido_id=pedido_id, acao=acao)

        _atualizar_status(pedido_id, novo_status)

        tracer.put_annotation(key="decisao_manual", value=novo_status)
        metrics.add_metric(name="PedidoDecididoManualmente", unit=MetricUnit.Count, value=1)
        metrics.add_dimension(name="Decisao", value=novo_status)

        logger.info("Pedido decidido manualmente", novo_status=novo_status)

        return _resposta(200, {"pedido_id": pedido_id, "status": novo_status})

    except _PedidoNaoEncontrado:
        logger.warning("Pedido não encontrado")
        return _resposta(404, {"erro": f"Pedido {pedido_id} não encontrado"})

    except _ConflitoDeEstado as e:
        logger.warning("Pedido não está elegível para decisão", status_atual=str(e))
        return _resposta(409, {
            "erro": f"Pedido está em '{e}', só pode ser decidido quando '{STATUS_ELEGIVEL}'"
        })

    except Exception as e:
        registrar_erro("decidir_pedido", e, pedido_id=pedido_id)
        return _resposta(500, {"erro": "Erro interno. Tente novamente."})


def _extrair_acao(event: dict) -> str | None:
    """Deriva a ação (aprovar/rejeitar) a partir do resource path da API."""
    resource = event.get("resource", "")
    for acao in ACOES:
        if resource.endswith(f"/{acao}"):
            return acao
    return None


@tracer.capture_method
def _atualizar_status(pedido_id: str, novo_status: str) -> None:
    """Atualiza o status apenas se o pedido estiver em 'aguardando_aprovacao'."""
    agora = datetime.now(timezone.utc).isoformat()
    try:
        table.update_item(
            Key={"pedido_id": pedido_id},
            UpdateExpression="SET #s = :novo_status, atualizado_em = :agora, decidido_em = :agora",
            ConditionExpression="attribute_exists(pedido_id) AND #s = :esperado",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":novo_status": novo_status,
                ":agora":       agora,
                ":esperado":    STATUS_ELEGIVEL,
            },
        )
        logger.debug("Status atualizado no DynamoDB", novo_status=novo_status)

    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # A condição falhou: pedido não existe OU está em outro status.
        # Uma leitura simples resolve a ambiguidade sem custo de escrita extra.
        pedido = table.get_item(Key={"pedido_id": pedido_id}).get("Item")
        if pedido is None:
            raise _PedidoNaoEncontrado() from e
        raise _ConflitoDeEstado(pedido.get("status", "desconhecido")) from e


def _resposta(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "application/json"},
        "body":       json.dumps(body, ensure_ascii=False, default=str),
    }
