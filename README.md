# Trade Genius

Time de robôs de investimento. **Por enquanto, só testes: nenhum robô compra ou vende nada.**

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

## Segurança

Este repositório é **público**. Nunca coloque chaves, senhas ou tokens aqui.
Use um arquivo `.env` (já está no `.gitignore`, então não sobe pro GitHub).

## Próximas fases

1. ✅ Preços
2. Histórico (backtest: média móvel 50/200 dias vs. comprar e segurar)
3. Robô de Risco
4. Paper trading (dinheiro de mentira) com relatório diário
5. Decisão: dinheiro real ou não
