"""Erros de negócio e de infraestrutura que a state machine sabe tratar.

O nome da classe vira o nome do erro no Step Functions, então
`ErrorEquals: ["PagamentoRecusado"]` casa com `PagamentoRecusado` aqui.
"""


class EstoqueInsuficiente(Exception):
    """Não há unidades disponíveis. Erro de negócio: não adianta repetir."""


class PagamentoRecusado(Exception):
    """O gateway recusou a cobrança. Erro de negócio: não adianta repetir."""


class ServicoIndisponivel(Exception):
    """Falha transitória de um serviço externo. Vale repetir com backoff."""


class ConfirmacaoFalhou(Exception):
    """Último passo do fluxo falhou depois de estoque e pagamento já feitos."""


class EstornoFalhou(Exception):
    """Simula uma compensação que também quebra."""
