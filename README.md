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

Roda sozinho no **GitHub Actions**, a cada 15 minutos, na conta **PAPER** da Alpaca (nunca a real: o código bloqueia `api.alpaca.markets`).

1. `execucao.py` pergunta a `sinais.py` o que fazer com BTC e ETH. **Duas estratégias rodam em paralelo**
   na mesma conta, cada uma com a sua carteira em `estado.json` (quantidade, preço de compra, stop, placar):
   - **rompimento**: fecha acima da máxima de N dias e da média de 200 = compra; fecha abaixo da mínima de M dias = vende.
     BTC: N=20, M=10. ETH: N=40, M=20. Stop = entrada − 2×ATR. Poucas operações: pode ter sido sorte.
   - **media**: comprado enquanto fecha acima da média de 50 dias; vende quando fecha abaixo. Stop móvel
     (começa em entrada − 2×ATR e sobe com o preço, nunca desce). Opera mais vezes (ver `backtest_momento.py`).
2. Só entra no dia do rompimento (não compra atrasado) e não recompra o mesmo sinal.
3. **Toda ordem passa pelo Robô de Risco.** Vetou = não envia.
4. `relatorio.py` escreve `relatorios/AAAA-MM-DD.md` (patrimônio, ordens, vetos).

As chaves ficam nos *secrets* do GitHub (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`). Nunca aparecem no código nem nos logs.

**Outras lógicas em `sinais.py`:** `medias` (50/200, a antiga) e `recuo` (comprar queda forte em tendência de alta), **desligada**: só liga com backtest aprovado e OK do Felipe. Para adicionar uma lógica: escreva a função, registre em `LOGICAS` e escolha em `USAR`.

**Parar tudo:** crie o arquivo `PARAR` no repositório (pelo site do GitHub: *Add file → Create new file*). Na próxima rodada (até 15 min), nenhuma ordem passa.

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

## Robô seletivo (backtest): só opera com sinal forte

`backtest_seletivo.py` testa estratégias que **esperam** um bom momento (poucas operações), em dados diários.
Os parâmetros são escolhidos só com dados antigos (walk-forward, janelas de 6 meses) e testados em 2024-01 a 2026-11, período que a escolha não viu.
Custo 0,15% por lado. Stop = entrada − k×ATR. Só comprado ou caixa.

- **A Tendência + recuo:** tendência de alta e o preço caiu forte (RSI(3) baixo) → compra; vende quando recupera.
- **B Rompimento:** fecha acima da máxima de N dias → compra; vende quando fecha abaixo da mínima de M dias.
- **+M:** não compra com o índice de Medo e Ganância (alternative.me, `data/fear_greed.csv`) em euforia.

| 2024-01 a 2026-11 | Operações | Retorno | Maior queda |
|---|---|---|---|
| BTC B Rompimento | 13 | +61% | -33% |
| BTC comprar e segurar | 1 | +37% | -53% |
| ETH B Rompimento | 6 | +69% | -23% |
| ETH comprar e segurar | 1 | -28% | -68% |
| Ficar em caixa | 0 | 0% | 0% |

A (recuo) perdeu dinheiro sem o filtro de Medo e Ganância. Detalhes: `python backtest_seletivo.py`.

**Cuidado:** o lucro do rompimento veio de 1 a 2 operações grandes (alta de 2024). Poucas operações e um só ciclo de cripto: pode ser sorte.
Passado não garante futuro.

## Tendência e momento (backtest): estratégias que operam mais

`backtest_momento.py` testa ideias de tendência em dados diários, com o mesmo teste honesto do robô seletivo
(walk-forward, janelas de 6 meses, teste 2024-01 a 2026-11, custo 0,15% por lado, stop k×ATR):
rompimento curto (10/20 dias), stop móvel, acima da média (20/50/100), cruzamento rápido de médias,
momento de L dias e rotação BTC/ETH.

| 2024-01 a 2026-11 | Operações | Retorno | Maior queda | Combinações que lucraram | Na conta (regra 1%) |
|---|---|---|---|---|---|
| BTC acima da média | 53 | +69% | -28% | 100% | +14% |
| BTC rompimento curto | 17 | +33% | -33% | 56% | +8% |
| BTC comprar e segurar | 1 | +37% | -53% | | |
| ETH acima da média | 36 | +84% | -47% | 100% | +8% |
| ETH momento 30 dias | 41 | +40% | -39% | 88% | +10% |
| ETH comprar e segurar | 1 | -28% | -68% | | |
| Rotação BTC/ETH | 85 | +16% | -39% | 75% | +4% |

**Escolhida para o paper: acima da média de 50 dias** (a que mais ganhou, com mais operações, e 100% das
combinações de parâmetros lucraram). Roda **ao lado** do rompimento, para comparar.

**Cuidados honestos:**
- Tirando as 2 melhores operações, o resultado fica negativo em TODAS as ideias de tendência. É a natureza
  delas: perdem pouco muitas vezes e ganham muito poucas vezes. Por isso elas precisam de tempo.
- "Na conta" é pequeno porque o Robô de Risco limita cada operação a 1% de risco (cerca de 10-12% da conta por compra).
- Hoje (2026-11-27) BTC e ETH estão abaixo das médias (BTC caiu ~29% e ETH ~37% em 60 dias):
  todas as estratégias de tendência dizem **caixa**. Ficar parado agora é o que evitou essas perdas.
- Um só ciclo de cripto. Passado não garante futuro.

## Teste de sinais rápidos (1 minuto)

`backtest_minuto.py` testa 4 sinais rápidos nos 30 dias de dados de 1 minuto da Binance
(`data/minuto/`). Escolhe o melhor ajuste nos primeiros 20 dias e prova nos últimos 10
(dias não usados para escolher). Custo: 0,10% taxa + 0,03% derrapagem por lado.

```bash
python backtest_minuto.py
```

Resultado na prova (16/11 a 26/11/2026), **com taxas**:

| Sinal | BTC | ETH | Trades/dia |
|---|---|---|---|
| Rompimento + volume (5 min) | -4,1% | -4,1% | ~1,5 |
| Cruzamento EMA (15 min) | -1,9% | -3,4% | ~1 |
| Reversão após queda (1 min) | -2,2% | -5,7% | ~0,6 |
| Momento (15 min) | -7,5% | -3,7% | ~1,5 |
| Comprar e segurar | -7,5% | -7,7% | - |
| Ficar parado em dinheiro | 0% | 0% | 0 |

**Todos perderam dinheiro.** "Ganharam" de comprar e segurar só porque o mercado caiu e eles
ficaram a maior parte do tempo fora. Ficar parado (0%) ganhou de todos.
No treino, quase nenhum ajuste deu lucro (0-3%; só a reversão no BTC teve 44%).
30 dias é pouquíssimo. Passado não garante futuro.
