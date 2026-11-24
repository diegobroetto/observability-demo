from erros import PagamentoRecusado, ServicoIndisponivel


def handler(event, _context):
    """Gateway de pagamento simulado. O campo `simular` escolhe o cenário de falha."""
    pedido_id = event["pedidoId"]
    cenario = event.get("simular", "nenhum")

    if cenario == "pagamento_recusado":
        raise PagamentoRecusado(f"Cartão recusado para o pedido {pedido_id}")
    if cenario == "gateway_instavel":
        raise ServicoIndisponivel("Gateway de pagamento fora do ar")

    # O id da cobrança é derivado do pedido: cobrar duas vezes o mesmo pedido gera o mesmo id.
    return {"cobrancaId": f"ch_{pedido_id}", "valor": event["valor"]}
