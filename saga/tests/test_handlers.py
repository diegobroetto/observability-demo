import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.update(
    AWS_DEFAULT_REGION="us-east-1",
    AWS_ACCESS_KEY_ID="test",
    AWS_SECRET_ACCESS_KEY="test",
    ESTOQUE_TABLE="estoque",
    RESERVAS_TABLE="reservas",
)


@pytest.fixture
def tabelas():
    with mock_aws():
        db = boto3.client("dynamodb")
        for nome, chave in (("estoque", "produtoId"), ("reservas", "pedidoId")):
            db.create_table(
                TableName=nome,
                AttributeDefinitions=[{"AttributeName": chave, "AttributeType": "S"}],
                KeySchema=[{"AttributeName": chave, "KeyType": "HASH"}],
                BillingMode="PAY_PER_REQUEST",
            )
        db.put_item(TableName="estoque", Item={"produtoId": {"S": "prod-camiseta"}, "disponivel": {"N": "10"}})
        yield db


def disponivel(db):
    item = db.get_item(TableName="estoque", Key={"produtoId": {"S": "prod-camiseta"}})["Item"]
    return int(item["disponivel"]["N"])


def pedido(**extra):
    base = {"pedidoId": "ped-1", "produtoId": "prod-camiseta", "quantidade": 2}
    base.update(extra)
    return base


def test_reservar_baixa_o_estoque(tabelas):
    import reservar_estoque

    resultado = reservar_estoque.handler(pedido(), None)
    assert resultado["reservado"] is True
    assert disponivel(tabelas) == 8


def test_reservar_repetido_nao_baixa_duas_vezes(tabelas):
    import reservar_estoque

    reservar_estoque.handler(pedido(), None)
    resultado = reservar_estoque.handler(pedido(), None)
    assert resultado["repetida"] is True
    assert disponivel(tabelas) == 8


def test_reservar_sem_estoque_levanta_erro_de_negocio(tabelas):
    import reservar_estoque
    from erros import EstoqueInsuficiente

    with pytest.raises(EstoqueInsuficiente):
        reservar_estoque.handler(pedido(quantidade=50), None)
    assert disponivel(tabelas) == 10


def test_liberar_devolve_o_estoque_uma_unica_vez(tabelas):
    import liberar_estoque
    import reservar_estoque

    reservar_estoque.handler(pedido(), None)
    assert liberar_estoque.handler(pedido(), None)["liberado"] is True
    assert disponivel(tabelas) == 10
    assert liberar_estoque.handler(pedido(), None)["liberado"] is False
    assert disponivel(tabelas) == 10


def test_liberar_sem_reserva_nao_inventa_estoque(tabelas):
    import liberar_estoque

    assert liberar_estoque.handler(pedido(), None)["liberado"] is False
    assert disponivel(tabelas) == 10


def test_cenarios_de_falha_dos_passos_simulados():
    import cobrar_pagamento
    import confirmar_pedido
    import estornar_pagamento
    from erros import ConfirmacaoFalhou, EstornoFalhou, PagamentoRecusado, ServicoIndisponivel

    with pytest.raises(PagamentoRecusado):
        cobrar_pagamento.handler({"pedidoId": "p", "valor": 1, "simular": "pagamento_recusado"}, None)
    with pytest.raises(ServicoIndisponivel):
        cobrar_pagamento.handler({"pedidoId": "p", "valor": 1, "simular": "gateway_instavel"}, None)
    with pytest.raises(ConfirmacaoFalhou):
        confirmar_pedido.handler({"pedidoId": "p", "simular": "confirmacao_falha"}, None)
    with pytest.raises(EstornoFalhou):
        estornar_pagamento.handler({"cobrancaId": "ch_p", "simular": "estorno_falha"}, None)
    assert cobrar_pagamento.handler({"pedidoId": "p", "valor": 1}, None)["cobrancaId"] == "ch_p"
