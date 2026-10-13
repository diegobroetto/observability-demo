"""
estoque_consumer/handler.py — consome fila SQS "Estoque"

LIÇÃO DESTE CONSUMER: visibility timeout vs. duração real do processamento.

A fila `EstoqueQueue` no template.yaml está configurada com:
    VisibilityTimeout: 180

...e a função tem Timeout: 30s. 180s = 6x o timeout, a régua que
a AWS recomenda (visibility timeout >= 6x o timeout da função, para cobrir
o pior caso de retry do Lambda).

SE VOCÊ REDUZIR o VisibilityTimeout da fila para, digamos, 10 segundos,
e essa função demorar mais que isso para processar (o sleep abaixo simula
uma chamada lenta a um sistema de estoque legado), o SQS vai considerar a
mensagem "não confirmada" e entregá-la de novo para outro worker ANTES do
primeiro terminar. Resultado: dois workers processando o mesmo pedido ao
mesmo tempo, estoque debitado em dobro.

Isso é fácil de reproduzir: troque VisibilityTimeout para 10 no template,
faça deploy, e observe `PedidoEstoqueDuplicado` subir no CloudWatch.
"""
import json, os, time, random
from decimal import Decimal
import boto3
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.batch.types import PartialItemFailureResponse

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
processor = BatchProcessor(event_type=EventType.SQS)

# Simula latência de um sistema de estoque legado — entre 3 e 15 segundos.
# Com VisibilityTimeout de 180s (correto) isso nunca causa duplicidade.
# Com VisibilityTimeout de 10s (o bug proposital) causa, com frequência.
LATENCIA_MIN_SEGUNDOS = 3
LATENCIA_MAX_SEGUNDOS = 15


@tracer.capture_method
def processar_registro(record: dict) -> None:
    detail = json.loads(record["body"]).get("detail", {})
    pedido_id = detail.get("pedido_id")
    produtos  = detail.get("produtos", [])

    logger.append_keys(pedido_id=pedido_id)

    latencia = random.uniform(LATENCIA_MIN_SEGUNDOS, LATENCIA_MAX_SEGUNDOS)
    logger.info("Iniciando baixa de estoque", produtos=len(produtos), latencia_simulada_s=round(latencia, 1))
    time.sleep(latencia)

    for produto in produtos:
        table.update_item(
            Key={"pedido_id": f"estoque#{produto.get('id', 'desconhecido')}"},
            UpdateExpression="SET ultima_baixa = :agora, ultimo_pedido = :pedido_id",
            ExpressionAttributeValues={":agora": Decimal(str(time.time())), ":pedido_id": pedido_id},
        )

    metrics.add_metric(name="EstoqueBaixado", unit=MetricUnit.Count, value=1)
    logger.info("Baixa de estoque concluída", duracao_real_s=round(latencia, 1))


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, context):
    # ReportBatchItemFailures também está ativo aqui — ver notificacao_consumer
    # para o comentário completo sobre por que isso importa.
    return process_partial_response(
        event=event,
        record_handler=processar_registro,
        processor=processor,
        context=context,
    )
