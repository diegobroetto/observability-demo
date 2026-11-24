# saga: Step Functions plugado no observability-demo

Saga de pedido (Step Functions Standard, JSONata, Python 3.13, arm64) para o artigo
"Step Functions e saga: como desfazer um pedido quando o pagamento falha".

A state machine escuta o `PedidoCriado` que o `criar_pedido` do projeto principal publica no
bus `pedidos-bus-dev` (source `observability-demo.pedidos`). Este é um stack separado: o deploy
do projeto principal não muda.

    NormalizarPedido -> ReservarEstoque -> CobrarPagamento -> ConfirmarPedido -> PedidoConfirmado

Falhas desfazem na ordem inversa (EstornarPagamento, LiberarEstoque) e terminam em `PedidoRecusado`.
Se a compensação falha depois das tentativas, termina em `CompensacaoFalhou`.

O evento real do `criar_pedido` traz `pedido_id`, `cliente_id` e `valor`, sem produto nem quantidade.
Nesse caso a saga assume `prod-camiseta` e quantidade 1 (ver `NormalizarPedido`).

## 1. Deploy

Primeiro suba o projeto principal (`sam deploy --config-env dev` na raiz), depois:

    cd saga
    sam build
    sam deploy

## 2. Estoque inicial

    scripts/seed-estoque.sh            # 10 unidades de prod-camiseta

## 3. Fluxo ponta a ponta (API real)

    curl -X POST "$API_URL/pedidos" -H 'Content-Type: application/json' \
      -d '{"cliente_id":"c-1","produtos":[{"id":"prod-camiseta","qtd":1}],"valor":99.9}'

O `criar_pedido` publica `PedidoCriado` e uma execução da saga começa. Veja em
Step Functions > PedidoSaga. Cada pedido consome 1 unidade; no 11º o estoque acaba e a saga
termina em `PedidoRecusado`.

## 4. Seis cenários (sem passar pela API)

    scripts/rodar-cenario.sh ok
    scripts/rodar-cenario.sh sem-estoque
    scripts/rodar-cenario.sh pagamento-recusado
    scripts/rodar-cenario.sh gateway-instavel
    scripts/rodar-cenario.sh confirmacao-falha
    scripts/rodar-cenario.sh estorno-falha

O campo `simular` do evento escolhe a falha. Confira o estoque e a tabela de reservas antes e depois.
`estorno-falha` leva alguns minutos: são 6 tentativas com backoff antes de `CompensacaoFalhou`.

## 5. Testes locais

    pip install pytest "moto[dynamodb]" boto3
    pytest tests

## 6. Limpeza

    sam delete --stack-name observability-demo-saga-dev

## Limitações

- O gateway de pagamento é simulado.
- Não há alarme para `CompensacaoFalhou`. Em produção, crie um.
- Confirme no histórico da primeira execução que o nome da exceção Python chega como nome do erro (Retry de `ServicoIndisponivel`).
