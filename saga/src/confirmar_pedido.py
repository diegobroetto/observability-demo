from erros import ConfirmacaoFalhou


def handler(event, _context):
    """Último passo do fluxo. Falhar aqui obriga a desfazer pagamento e estoque."""
    if event.get("simular") in ("confirmacao_falha", "estorno_falha"):
        raise ConfirmacaoFalhou(f"Não foi possível confirmar o pedido {event['pedidoId']}")
    return {"pedidoId": event["pedidoId"], "status": "CONFIRMADO"}
