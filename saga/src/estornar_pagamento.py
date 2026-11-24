from erros import EstornoFalhou


def handler(event, _context):
    """Compensação de CobrarPagamento."""
    if event.get("simular") == "estorno_falha":
        raise EstornoFalhou(f"Gateway não aceitou o estorno de {event['cobrancaId']}")
    return {"estornoId": f"re_{event['cobrancaId']}"}
