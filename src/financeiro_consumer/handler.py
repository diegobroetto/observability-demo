"""
financeiro_consumer/handler.py — consome fila SQS "Financeiro"

LIÇÃO DESTE CONSUMER: DLQ configurada corretamente, de ponta a ponta.

Diferente do estoque_consumer (bug de timing) e do notificacao_consumer
(processamento parcial), este consumer demonstra o caminho feliz de uma
falha PERSISTENTE — não uma falha passageira que um retry resolve, mas um
erro de negócio que vai continuar falhando não importa quantas vezes o SQS
tente de novo (ex.: dados de cobrança inválidos vindos do pedido).

A fila `FinanceiroQueue` tem:
    RedrivePolicy:
      deadLetterTargetArn: !GetAtt FinanceiroDLQ.Arn
      maxReceiveCount: 3

Depois de 3 tentativas malsucedidas, o SQS move a mensagem automaticamente
para a FinanceiroDLQ — sem intervenção do código abaixo. O papel deste
handler é só falhar de forma HONESTA quando o erro é irrecuperável (deixar
a exceção subir), em vez de engolir o erro e devolver sucesso falso.

O erro mais comum aqui NÃO é de código — é esquecer de colocar um alarme
em `ApproximateNumberOfMessagesVisible` da própria DLQ. Sem esse alarme,
mensagens podem se acumular na DLQ silenciosamente por semanas até alguém
notar que cobranças pararam de ser geradas para uma fatia de pedidos.
Ver o alarme `FinanceiroDLQAlarm` no template.yaml.
"""
import json, os, random
from decimal import Decimal, InvalidOperation
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response

processor = BatchProcessor(event_type=EventType.SQS)

# Simula um percentual de pedidos com dado de cobrança inválido — erro
# permanente, não passageiro. Faz sentido ir para DLQ, não adianta retry.
TAXA_ERRO_PERMANENTE = 0.10


@tracer.capture_method
def processar_registro(record: dict) -> None:
    detail = json.loads(record["body"]).get("detail", {})
    pedido_id = detail.get("pedido_id")
    valor = detail.get("valor")

    logger.append_keys(pedido_id=pedido_id)

    if random.random() < TAXA_ERRO_PERMANENTE:
        # Erro permanente de propósito — nenhuma quantidade de retry resolve
        # "valor de cobrança inválido". Isso é o que deve ir para a DLQ
        # depois de esgotar o maxReceiveCount, não ficar em loop infinito.
        raise InvalidOperation(f"Valor de cobrança inválido para pedido {pedido_id}: {valor}")

    valor_decimal = Decimal(str(valor))
    logger.info("Cobrança gerada", valor=float(valor_decimal))
    metrics.add_metric(name="CobrancaGerada", unit=MetricUnit.Count, value=1)


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, context):
    return process_partial_response(
        event=event,
        record_handler=processar_registro,
        processor=processor,
        context=context,
    )
