"""
notificacao_consumer/handler.py — consome fila SQS "Notificação"

LIÇÃO DESTE CONSUMER: ReportBatchItemFailures — processar parcial, não
perder o lote inteiro.

O event source mapping do SQS entrega até `BatchSize` mensagens de uma vez
(ver template.yaml — BatchSize: 10). SEM `ReportBatchItemFailures` ativo, se
UMA mensagem do lote de 10 falhar, o Lambda relata falha do lote inteiro
para o SQS — e as outras 9 mensagens, que já tinham processado com sucesso
(enviaram e-mail, etc.), voltam para a fila e são reprocessadas. Resultado:
cliente recebe o mesmo e-mail de confirmação repetido várias vezes.

A versão ERRADA seria assim — sem controle de item, um throw derruba tudo:

    def lambda_handler(event, context):
        for record in event["Records"]:
            enviar_notificacao(record)   # se UMA lançar exceção, TODAS voltam pra fila

A versão abaixo usa o utilitário de batch do Powertools, que:
  1. Processa cada mensagem isoladamente
  2. Captura falha por mensagem individual
  3. Reporta ao SQS SÓ os message_id que falharam (via `batchItemFailures`)
  4. As mensagens que tiveram sucesso são removidas da fila normalmente

Para isso funcionar, o Event Source Mapping do SQS precisa ter
`FunctionResponseTypes: [ReportBatchItemFailures]` — ver template.yaml.
Sem essa flag, a invocação termina sem erro e o Lambda apaga do SQS o lote
inteiro, inclusive as mensagens que falharam (que somem sem ir para a DLQ).
Só quando TODAS falham o BatchProcessor lança erro e o lote volta. É um erro fácil de cometer:
configurar certo no código e esquecer no template.
"""
import json, os, random
from observability import logger, tracer, metrics, registrar_erro
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response

processor = BatchProcessor(event_type=EventType.SQS)

# Simula falha intermitente de um provedor de e-mail/SMS — 25% de chance.
# Serve para forçar lotes mistos (parte sucesso, parte falha) e mostrar
# a diferença de comportamento com e sem ReportBatchItemFailures.
TAXA_FALHA_SIMULADA = 0.25


@tracer.capture_method
def processar_registro(record: dict) -> None:
    detail = json.loads(record["body"]).get("detail", {})
    pedido_id = detail.get("pedido_id")
    cliente_id = detail.get("cliente_id")

    logger.append_keys(pedido_id=pedido_id, cliente_id=cliente_id)

    if random.random() < TAXA_FALHA_SIMULADA:
        # Propositalmente lançada para simular timeout do provedor de e-mail.
        # Com BatchProcessor, só ESTA mensagem volta para a fila — as demais
        # do lote seguem seu fluxo normal.
        raise RuntimeError("Timeout simulado no provedor de notificação")

    logger.info("Notificação enviada ao cliente", canal="email")
    metrics.add_metric(name="NotificacaoEnviada", unit=MetricUnit.Count, value=1)


@logger.inject_lambda_context(log_event=os.environ.get("LOG_EVENT") == "true")
@tracer.capture_lambda_handler(capture_response=False)
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, context):
    resultado = process_partial_response(
        event=event,
        record_handler=processar_registro,
        processor=processor,
        context=context,
    )

    falhas = len(resultado.get("batchItemFailures", []))
    if falhas:
        logger.warning("Lote com falhas parciais", falhas=falhas, total=len(event["Records"]))
        metrics.add_metric(name="NotificacaoFalhaParcial", unit=MetricUnit.Count, value=falhas)

    return resultado
