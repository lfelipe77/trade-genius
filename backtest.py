"""Fase 2: Robô de Histórico (backtest).

Compara duas estratégias no passado, para BTC-USD e ETH-USD:
  1. Cruzamento de médias móveis 50/200 dias: comprado quando a média de 50
     está acima da de 200, em dinheiro (caixa) quando está abaixo.
  2. Comprar e segurar (buy-and-hold).

Regras para ser honesto:
  - Sem "olhar o futuro": o sinal é calculado no fechamento de um dia e a
    operação acontece no dia seguinte.
  - Custos em toda compra e venda: taxa 0,10% + derrapagem (slippage) 0,05%.
  - As duas estratégias começam no MESMO dia (quando a média de 200 já existe).
  - O último dia do CSV (incompleto) é ignorado.

Resultado passado não garante nada no futuro. 5 anos é pouco histórico.

Uso: python backtest.py
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
TICKERS = ["BTC-USD", "ETH-USD"]
FAST, SLOW = 50, 200
FEE = 0.0010       # 0,10% por operação (taxa típica de corretora)
SLIPPAGE = 0.0005  # 0,05% por operação (preço pior que o esperado)
COST = FEE + SLIPPAGE


def load(ticker: str) -> pd.Series:
    df = pd.read_csv(DATA_DIR / f"{ticker}.csv", parse_dates=["Date"], index_col="Date")
    close = df["Close"].dropna()
    return close.iloc[:-1]  # último dia ainda está incompleto


def max_drawdown(equity: pd.Series) -> float:
    """Maior queda do pico até o fundo (ex.: -0.55 = caiu 55%)."""
    return float((equity / equity.cummax() - 1).min())


def run(ticker: str) -> dict:
    close = load(ticker)
    fast = close.rolling(FAST).mean()
    slow = close.rolling(SLOW).mean()

    # 1 = comprado, 0 = caixa. Posição de hoje = sinal de ontem.
    signal = (fast > slow).astype(int)
    position = signal.shift(1)

    # Período comum: a partir do primeiro dia com posição definida.
    start = slow.first_valid_index()
    start = close.index[close.index.get_loc(start) + 1]
    close, position = close.loc[start:], position.loc[start:]

    daily_ret = close.pct_change().fillna(0)

    # --- Estratégia de médias móveis ---
    trades = position.diff().abs()
    trades.iloc[0] = position.iloc[0]  # entrada no primeiro dia, se comprado
    strat_ret = position * daily_ret - trades * COST
    strat_equity = (1 + strat_ret).cumprod()

    # --- Comprar e segurar (paga 1 compra no início) ---
    bh_ret = daily_ret.copy()
    bh_ret.iloc[0] -= COST
    bh_equity = (1 + bh_ret).cumprod()

    return {
        "ticker": ticker,
        "start": close.index[0].date(),
        "end": close.index[-1].date(),
        "strat_return": strat_equity.iloc[-1] - 1,
        "strat_dd": max_drawdown(strat_equity),
        "strat_trades": int(trades.sum()),
        "strat_time_in": float(position.mean()),
        "bh_return": bh_equity.iloc[-1] - 1,
        "bh_dd": max_drawdown(bh_equity),
    }


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def main() -> None:
    print(f"Backtest médias {FAST}/{SLOW} vs comprar e segurar")
    print(f"Custo por operação: {COST * 100:.2f}% (taxa {FEE * 100:.2f}% + derrapagem {SLIPPAGE * 100:.2f}%)\n")
    for t in TICKERS:
        r = run(t)
        venceu = "SIM" if r["strat_return"] > r["bh_return"] else "NÃO"
        print(f"== {t}  ({r['start']} a {r['end']}) ==")
        print(f"  {'':22}{'Médias 50/200':>15}{'Comprar e segurar':>20}")
        print(f"  {'Retorno total':22}{pct(r['strat_return']):>15}{pct(r['bh_return']):>20}")
        print(f"  {'Maior queda':22}{pct(r['strat_dd']):>15}{pct(r['bh_dd']):>20}")
        print(f"  {'Nº de operações':22}{r['strat_trades']:>15}{1:>20}")
        print(f"  {'Tempo comprado':22}{r['strat_time_in'] * 100:>14.0f}%{100:>19}%")
        print(f"  Médias venceram depois dos custos? {venceu}\n")
    print("Atenção: passado não garante futuro. 5 anos é pouco histórico.")


if __name__ == "__main__":
    main()
