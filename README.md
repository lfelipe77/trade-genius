# Trade Genius

Time de robôs de investimento. **Por enquanto, só dinheiro de mentira (paper trading). Nenhum dinheiro real.**

## Fase 1: Robô de Preços

Baixa 5 anos de preços diários do **Bitcoin (BTC-USD)** e do **Ethereum (ETH-USD)**,
de graça, pelo Yahoo Finance (biblioteca `yfinance`), e salva em:

- `data/BTC-USD.csv`
- `data/ETH-USD.csv`

Cada linha é um dia: `Date, Open, High, Low, Close, Adj Close, Volume` (preços em dólar).
A última linha é o dia de hoje, ainda incompleto.

### Como rodar

```bash
pip install -r requirements.txt
python precos.py
```

Ele substitui os CSVs pelos dados mais novos.

## Fase 2: Robô de Histórico (backtest)

Testa no passado: **médias móveis 50/200 dias** (comprado quando a média de 50 está acima da de 200, em caixa quando está abaixo) contra **comprar e segurar**.

- Sinal calculado no fechamento, operação no dia seguinte (sem "olhar o futuro").
- Custo em toda compra/venda: 0,10% de taxa + 0,05% de derrapagem.
- As duas começam no mesmo dia (quando a média de 200 já existe).

```bash
python backtest.py
```

Resultado com os dados de 2022-06-14 a 2026-11-25:

| | Médias 50/200 | Comprar e segurar |
|---|---|---|
| BTC retorno | +42,4% | +171,5% |
| BTC maior queda | -53,1% | -53,1% |
| ETH retorno | -28,6% | +39,3% |
| ETH maior queda | -68,9% | -67,6% |
| Operações (cada) | 9 | 1 |

**Neste período, as médias perderam para comprar e segurar nos dois casos.**
Passado não garante futuro, e 5 anos é pouco histórico.

## Fase 3: Robô de Risco

Regras fixas em código (**sem IA**) em `risco.py`. Toda ordem passa por ele antes de ir para a corretora, e ele pode **vetar**.

| Regra | Padrão |
|---|---|
| Risco máximo por trade (preço − stop, + custos) | 1% da conta |
| Limite de perda no dia (bateu: só vendas até amanhã) | 3% |
| Compra sem stop | vetada |
| Alavancagem / venda a descoberto | proibidas |
| Botão de parar | bloqueia **todas** as ordens |

Os valores ficam em `risco_config.json` (sem chaves, sem senhas).

**Botão de parar:** crie um arquivo chamado `PARAR` na pasta do projeto (ou mude `"parar_tudo"` para `true` no config). Apague o arquivo para liberar de novo.

```bash
python risco.py              # exemplos de ordens aprovadas e vetadas
python -m unittest -v        # testes
```

## Fase 4: Paper trading (dinheiro de mentira)

Roda sozinho no **GitHub Actions**, de hora em hora, na conta **PAPER** da Alpaca (nunca a real: o código bloqueia `api.alpaca.markets`).

1. `execucao.py` calcula as médias 50/200 de BTC e ETH.
   **Atenção:** essa estratégia perdeu para comprar e segurar no backtest. Aqui ela só testa a mecânica.
2. Compra com stop 5% abaixo. Vende se o sinal virar ou se bater no stop.
3. **Toda ordem passa pelo Robô de Risco.** Vetou = não envia.
4. `relatorio.py` escreve `relatorios/AAAA-MM-DD.md` (patrimônio, ordens, vetos).

As chaves ficam nos *secrets* do GitHub (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`). Nunca aparecem no código nem nos logs.

**Parar tudo:** crie o arquivo `PARAR` no repositório (pelo site do GitHub: *Add file → Create new file*). Na próxima hora, nenhuma ordem passa.

```bash
python checar_chaves.py      # testa as chaves (mostra só o status da conta)
python execucao.py --simular # calcula e passa no risco, sem enviar ordem
python relatorio.py          # relatório do dia
```

## Segurança

Este repositório é **público**. Nunca coloque chaves, senhas ou tokens aqui.
Use um arquivo `.env` (já está no `.gitignore`, então não sobe pro GitHub).

## Próximas fases

1. ✅ Preços
2. ✅ Histórico (backtest: média móvel 50/200 dias vs. comprar e segurar)
3. ✅ Risco
4. ✅ Paper trading (dinheiro de mentira) com relatório diário
5. Decisão: dinheiro real ou não
