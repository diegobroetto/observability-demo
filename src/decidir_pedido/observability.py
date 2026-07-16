"""
observability.py — utilitários compartilhados de observabilidade

Em um projeto real, este módulo ficaria em um layer próprio de utilitários
ou em um pacote interno. Aqui está duplicado por simplicidade de exemplo.

Centraliza a configuração de Logger, Tracer e Metrics do Powertools para
garantir consistência entre funções.
"""

import os
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

SERVICE_NAME = os.environ.get("POWERTOOLS_SERVICE_NAME", "observability-demo")
NAMESPACE    = "observability-demo/Pedidos"

# ---------------------------------------------------------------------------
# Logger — structured JSON com correlation ID automático
#
# O Powertools adiciona automaticamente:
#   - cold_start (bool)
#   - function_name, function_memory_size, function_arn, function_request_id
#   - timestamp, level, service
#
# log_event=False em prod: evita logar o payload completo do evento,
# que pode conter dados sensíveis e aumentar custo de ingestão.
# ---------------------------------------------------------------------------
logger = Logger(
    service=SERVICE_NAME,
    log_uncaught_exceptions=True,   # loga exceções não tratadas automaticamente
)

# ---------------------------------------------------------------------------
# Tracer — X-Ray sem boilerplate
#
# capture_response=False em prod: evita adicionar o response completo
# ao trace, que pode conter dados sensíveis e aumentar custo de X-Ray.
# ---------------------------------------------------------------------------
tracer = Tracer(service=SERVICE_NAME)

# ---------------------------------------------------------------------------
# Metrics — Embedded Metric Format (EMF)
#
# EMF emite métricas customizadas dentro do log JSON.
# O CloudWatch processa o log e cria a métrica automaticamente.
# Sem chamada de API extra por invocação — mais eficiente que put_metric_data.
# ---------------------------------------------------------------------------
metrics = Metrics(namespace=NAMESPACE, service=SERVICE_NAME)


def registrar_erro(operacao: str, erro: Exception, **contexto) -> None:
    """Registra um erro de forma padronizada com contexto adicional."""
    logger.error(
        "Erro na operação",
        operacao=operacao,
        tipo_erro=type(erro).__name__,
        mensagem_erro=str(erro),
        **contexto,
    )
    metrics.add_metric(
        name="ErroOperacao",
        unit=MetricUnit.Count,
        value=1,
    )
    metrics.add_dimension(name="Operacao", value=operacao)
