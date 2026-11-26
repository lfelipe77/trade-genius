"""Robô seletivo (backtest): só opera quando aparece um sinal forte.

Ideia do Felipe: não apostar toda hora. Esperar um momento bom, comprar,
e vender quando o motivo acabar (ou o stop bater). Só "comprado" ou "caixa":
sem venda a descoberto e sem alavancagem (regras do Robô de Risco).

Estratégias testadas (dados diários, BTC-USD e ETH-USD):
  A. Tendência + recuo: preço acima da média de T dias (tendência de alta)
     e o RSI(3) caiu abaixo de X (recuo forte). Sai quando o RSI(3) passa
     de 65, depois de 15 dias, ou no stop.
  B. Rompimento: fecha acima da máxima dos últimos N dias, acima da média de
     200, e (opcional) com volatilidade baixa antes (mola comprimida).
     Sai quando fecha abaixo da mínima dos últimos M dias, ou no stop.
  A+M / B+M: iguais, mas NÃO compram se o índice de Medo e Ganância
     (alternative.me, grátis) estiver acima de G (euforia).
Todas têm stop = entrada - k x ATR(14), checado na mínima do dia.

Teste honesto (walk-forward):
  - Os parâmetros são escolhidos SÓ com dados anteriores a cada janela de
    teste de 6 meses (2024-01 até 2026-11). Depois a estratégia roda nessa
    janela sem ver o futuro. As janelas são coladas uma na outra.
  - Custo em toda compra e venda: 0,10% de taxa + 0,05% de derrapagem.
  - Sinal no fechamento do dia, operação no mesmo preço de fechamento
    (cripto é 24h, o fechamento é quase igual à abertura seguinte).

Cuidado: 2022-2026 é basicamente UM ciclo de cripto e poucas operações.
Resultado passado não garante nada no futuro.

Uso: python backtest_seletivo.py
"""

from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
TICKERS = ["BTC-USD", "ETH-USD"]
COST = 0.0010 + 0.0005  # taxa + derrapagem, por lado
TRAIN_START = "2022-06-15"  # média de 200 já existe
WINDOWS = [
    ("2024-01-01", "2024-06-30"),
    ("2024-07-01", "2024-12-31"),
    ("2025-01-01", "2025-06-30"),
    ("2025-07-01", "2025-12-31"),
    ("2026-01-01", "2026-12-31"),
]
MIN_TRADES_TRAIN = 3  # menos que isso no treino = não dá para escolher


# ---------------------------------------------------------------- dados
def load(ticker: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{ticker}.csv", parse_dates=["Date"], index_col="Date")
    df = df[["Open", "High", "Low", "Close"]].dropna().iloc[:-1]  # hoje incompleto
    fg = pd.read_csv(DATA_DIR / "fear_greed.csv", parse_dates=["Date"], index_col="Date")
    df["fng"] = fg["fng"].reindex(df.index).ffill()
    return add_indicators(df)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Só usa o passado (janelas que olham para trás)."""
    df = df[["Open", "High", "Low", "Close", "fng"]].copy()
    c = df["Close"]
    prev = c.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - prev).abs(), (df.Low - prev).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["atr_pct"] = df.atr / c
    df["atr_med"] = df.atr_pct.rolling(180).median()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 3, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 3, adjust=False).mean()
    df["rsi3"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    for n in (50, 100, 200):
        df[f"sma{n}"] = c.rolling(n).mean()
    for n in (20, 40, 60):
        df[f"hh{n}"] = df.High.rolling(n).max().shift(1)
    for m in (10, 20):
        df[f"ll{m}"] = df.Low.rolling(m).min().shift(1)
    return df


# ---------------------------------------------------------------- regras
def entry_exit(df: pd.DataFrame, kind: str, p: dict):
    c = df.Close
    fg_ok = df.fng <= p.get("g", 101)
    if kind == "A":
        entry = (c > df[f"sma{p['t']}"]) & (df.rsi3 < p["x"]) & fg_ok
        exit_ = df.rsi3 > 65
        max_hold = 15
    else:
        entry = (c > df[f"hh{p['n']}"]) & (c > df.sma200) & fg_ok
        if p["vol"]:
            entry &= df.atr_pct.shift(1) < df.atr_med.shift(1)
        exit_ = c < df[f"ll{p['m']}"]
        max_hold = 10_000
    return entry.fillna(False).values, exit_.fillna(False).values, max_hold


def simulate(df: pd.DataFrame, kind: str, p: dict):
    """Retorna (retorno diário líquido, posição no fim do dia, lista de trades)."""
    entry, exit_, max_hold = entry_exit(df, kind, p)
    o, h, lo, c, atr = (df[k].values for k in ("Open", "High", "Low", "Close", "atr"))
    n = len(df)
    ret = np.zeros(n)
    pos = np.zeros(n)
    trades = []
    in_pos, ep, stop, held, edate = False, 0.0, 0.0, 0, None
    for i in range(1, n):
        if in_pos:
            held += 1
            if lo[i] <= stop:  # stop bateu durante o dia
                px = min(o[i], stop)
                ret[i] = px / c[i - 1] - 1 - COST
                trades.append((edate, df.index[i], px / ep - 1 - 2 * COST))
                in_pos = False
                continue  # não recompra no mesmo dia
            ret[i] = c[i] / c[i - 1] - 1
            if exit_[i] or held >= max_hold:
                ret[i] -= COST
                trades.append((edate, df.index[i], c[i] / ep - 1 - 2 * COST))
                in_pos = False
        elif entry[i] and not np.isnan(atr[i]):
            in_pos, ep, held, edate = True, c[i], 0, df.index[i]
            stop = c[i] - p["k"] * atr[i]
            ret[i] = -COST
        pos[i] = 1.0 if in_pos else 0.0
    return pd.Series(ret, df.index), pd.Series(pos, df.index), trades


def grid(kind: str, with_fg: bool):
    gs = [70, 80, 90] if with_fg else [101]
    if kind == "A":
        for t, x, k, g in product([50, 100, 200], [10, 20, 30], [2, 3], gs):
            yield {"t": t, "x": x, "k": k, "g": g}
    else:
        for n, m, vol, k, g in product([20, 40, 60], [10, 20], [0, 1], [2, 3], gs):
            yield {"n": n, "m": m, "vol": vol, "k": k, "g": g}


# ---------------------------------------------------------------- métricas
def max_dd(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min())


def walk_forward(df: pd.DataFrame, kind: str, with_fg: bool):
    params = list(grid(kind, with_fg))
    sims = [simulate(df, kind, p) for p in params]
    oos_ret, oos_pos, oos_trades, chosen = [], [], [], []
    prev_pos = 0.0
    for start, end in WINDOWS:
        best, best_score = None, -np.inf
        for j, (r, _, tr) in enumerate(sims):
            ntr = sum(1 for t in tr if TRAIN_START <= str(t[1].date()) < start)
            if ntr < MIN_TRADES_TRAIN:
                continue
            score = (1 + r.loc[TRAIN_START:start].iloc[:-1]).prod()
            if score > best_score:
                best, best_score = j, score
        r, pos, tr = sims[best]
        w = r.loc[start:end].copy()
        # Troca de parâmetros na virada da janela: se a posição muda, paga custo.
        before = pos.loc[:start].iloc[:-1].iloc[-1] if pos.index[0] < pd.Timestamp(start) else 0.0
        if before != prev_pos:
            w.iloc[0] -= COST
        oos_ret.append(w)
        oos_pos.append(pos.loc[start:end])
        prev_pos = pos.loc[start:end].iloc[-1]
        oos_trades += [t for t in tr if start <= str(t[0].date()) <= end]
        chosen.append((start, params[best], best_score - 1))
    ret = pd.concat(oos_ret)
    pos = pd.concat(oos_pos)
    eq = (1 + ret).cumprod()
    return {
        "ret": eq.iloc[-1] - 1,
        "dd": max_dd(eq),
        "trades": len(oos_trades),
        "wins": sum(1 for t in oos_trades if t[2] > 0),
        "time_in": float(pos.mean()),
        "chosen": chosen,
        "trade_list": oos_trades,
        "pos_windows": sum(1 for s, e in WINDOWS if (1 + ret.loc[s:e]).prod() > 1),
    }


def robustness(df: pd.DataFrame, kind: str, with_fg: bool):
    """Todas as combinações de parâmetros, fixas, no período de teste inteiro.
    Se só UMA combinação ganha, é sorte; se a maioria ganha, a ideia é mais sólida."""
    start = WINDOWS[0][0]
    outs = []
    for p in grid(kind, with_fg):
        r, _, _ = simulate(df, kind, p)
        outs.append((1 + r.loc[start:]).prod() - 1)
    outs = np.array(outs)
    return float((outs > 0).mean()), float(np.median(outs))


def buy_hold(df: pd.DataFrame):
    c = df.Close.loc[WINDOWS[0][0]:]
    r = c.pct_change().fillna(0)
    r.iloc[0] -= COST
    eq = (1 + r).cumprod()
    return eq.iloc[-1] - 1, max_dd(eq), c.index[0].date(), c.index[-1].date()


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


NAMES = {
    ("A", False): "A Tendência+recuo",
    ("A", True): "A+M (c/ Medo&Ganância)",
    ("B", False): "B Rompimento",
    ("B", True): "B+M (c/ Medo&Ganância)",
}


def main() -> None:
    print("Robô seletivo: walk-forward, custo 0,15% por lado\n")
    for t in TICKERS:
        df = load(t)
        bh, bh_dd, s, e = buy_hold(df)
        print(f"== {t}  teste fora da amostra: {s} a {e} ==")
        print(f"  {'Estratégia':26}{'Operações':>10}{'Acertos':>9}{'Retorno':>10}{'Maior queda':>13}{'Tempo comprado':>16}{'Janelas +':>11}")
        for (kind, fg), name in NAMES.items():
            r = walk_forward(df, kind, fg)
            share, med = robustness(df, kind, fg)
            print(f"  {name:26}{r['trades']:>10}{r['wins']:>9}{pct(r['ret']):>10}{pct(r['dd']):>13}"
                  f"{r['time_in'] * 100:>15.0f}%{r['pos_windows']:>8}/{len(WINDOWS)}")
            print(f"      robustez: {share * 100:.0f}% das combinações lucraram no teste (mediana {pct(med)})")
            for start, p, score in r["chosen"]:
                print(f"      janela {start}: params {p} (treino {pct(score)})")
        print(f"  {'Comprar e segurar':26}{1:>10}{'':>9}{pct(bh):>10}{pct(bh_dd):>13}{100:>15}%")
        print(f"  {'Ficar em caixa':26}{0:>10}{'':>9}{pct(0):>10}{pct(0):>13}{0:>15}%\n")
    print("Atenção: poucas operações e um só ciclo de cripto. Passado não garante futuro.")


if __name__ == "__main__":
    main()
