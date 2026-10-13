"""observability.py — utilitários compartilhados de Logger, Tracer e Metrics (Powertools)."""
import os
from aws_lambda_powertools import Logger, Tracer, Metrics

SERVICE_NAME = os.environ.get("POWERTOOLS_SERVICE_NAME", "observability-demo")
NAMESPACE    = "observability-demo/Pedidos"

logger  = Logger(service=SERVICE_NAME, log_uncaught_exceptions=True)
tracer  = Tracer(service=SERVICE_NAME)
metrics = Metrics(namespace=NAMESPACE, service=SERVICE_NAME)


def registrar_erro(operacao: str, erro: Exception, **contexto) -> None:
    logger.error(
        "Erro na operação",
        operacao=operacao,
        tipo_erro=type(erro).__name__,
        mensagem_erro=str(erro),
        **contexto,
    )
