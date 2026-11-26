"""Backtest de sinais rápidos (dados de 1 minuto da Binance, 30 dias).

Pergunta: um robô que olha o mercado a cada 1-5 minutos e só opera quando
aparece um sinal forte ganha de "comprar e segurar", DEPOIS das taxas?

Como é honesto (walk-forward):
  - Dias 1-20 ("treino"): testamos vários ajustes de cada sinal e escolhemos
    o melhor (pelo retorno líquido no treino).
  - Dias 21-30 ("prova"): rodamos SÓ o ajuste escolhido, em dias que não
    foram usados para escolher. É esse número que importa.
  - Sinal no fechamento da barra; compra/venda no ABRIR da barra seguinte.
  - Só compra (sem venda a descoberto), sempre com stop (como o Robô de Risco).
  - Se a barra toca o stop e o alvo, assumimos o pior (stop).
  - Custos por lado: taxa Binance 0,10% (taker) + derrapagem 0,03%.

Sinais testados:
  1. Rompimento + volume (barras de 5 min): fecha acima da máxima das últimas
     N barras com volume > k x a média -> compra; sai no alvo, stop ou tempo.
  2. Cruzamento de médias EMA (barras de 15 min): comprado enquanto a rápida
     está acima da lenta; stop de segurança.
  3. Reversão após queda forte (barras de 1 min): caiu X% em M minutos ->
     compra; sai no alvo, stop ou tempo.
  4. Momento (barras de 15 min): subiu X% nas últimas L barras -> compra e
     segura H barras (com stop).

ATENÇÃO: 30 dias é uma amostra MUITO curta. O risco principal é "overfitting"
(achar um ajuste que só funcionou por sorte nesses dias). A maioria das
estratégias de minuto perde dinheiro depois das taxas.

Uso: python backtest_minuto.py
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data" / "minuto"
SYMBOLS = {"BTC": "binance_BTCUSDT_1m.csv.gz", "ETH": "binance_ETHUSDT_1m.csv.gz"}
FEE = 0.0010       # taxa taker Binance spot, por lado
SLIPPAGE = 0.0003  # derrapagem estimada, por lado
COST = FEE + SLIPPAGE
TRAIN_DAYS = 20
MIN_TRAIN_TRADES = 5  # ajuste com menos trades que isso no treino é descartado


# ---------------------------------------------------------------- dados ----

def load(file: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / file, parse_dates=["timestamp_utc"], index_col="timestamp_utc")
    df = df[~df.index.duplicated()].sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes == 1:
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df.resample(f"{minutes}min", label="left", closed="left").agg(agg).dropna()


# ------------------------------------------------------------ simulador ----

@dataclass
class Result:
    trades: int
    wins: int
    gross: float     # retorno total sem custos
    net: float       # retorno total com custos
    max_dd: float    # maior queda (com custos)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0


def simulate(bars: pd.DataFrame, entry: np.ndarray, exit_sig: np.ndarray | None,
             stop: float, target: float | None, max_hold: int | None,
             start: int, end: int) -> Result:
    """Simula trades entre as barras [start, end). Uma posição por vez, 100% do capital.

    entry[i]/exit_sig[i] = sinal no FECHAMENTO da barra i -> ordem no abrir de i+1.
    """
    o, h, l, c = (bars[k].to_numpy() for k in ("open", "high", "low", "close"))
    eq_gross = eq_net = 1.0
    peak = 1.0
    max_dd = 0.0
    trades = wins = 0
    i = start
    while i < end - 1:
        if not entry[i]:
            i += 1
            continue
        j = i + 1
        px_in = o[j]
        stop_px = px_in * (1 - stop)
        tgt_px = px_in * (1 + target) if target else np.inf
        px_out = None
        while j < end:
            # mark-to-market para a maior queda (pior ponto da barra)
            worst = max(l[j], stop_px)
            mtm = eq_net * (worst * (1 - COST)) / (px_in * (1 + COST))
            peak = max(peak, eq_net)
            max_dd = min(max_dd, mtm / peak - 1)
            if l[j] <= stop_px:
                px_out = min(o[j], stop_px)  # se abriu abaixo do stop, sai no abrir
                break
            if h[j] >= tgt_px:
                px_out = max(o[j], tgt_px)
                break
            held = j - i
            if (exit_sig is not None and exit_sig[j]) or (max_hold and held >= max_hold):
                if j + 1 < end:
                    px_out = o[j + 1]
                    j += 1
                else:
                    px_out = c[j]
                break
            j += 1
        if px_out is None:  # acabou o período com posição aberta: fecha no último preço
            j = end - 1
            px_out = c[j]
        r_gross = px_out / px_in
        r_net = (px_out * (1 - COST)) / (px_in * (1 + COST))
        eq_gross *= r_gross
        eq_net *= r_net
        trades += 1
        wins += r_net > 1
        peak = max(peak, eq_net)
        max_dd = min(max_dd, eq_net / peak - 1)
        i = j  # pode entrar de novo a partir da barra da saída
    return Result(trades, wins, eq_gross - 1, eq_net - 1, max_dd)


# --------------------------------------------------------------- sinais ----

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sig_breakout(b: pd.DataFrame, n: int, vol_k: float, **_) -> tuple:
    prior_high = b["high"].rolling(n).max().shift(1)
    vol_avg = b["volume"].rolling(n).mean().shift(1)
    entry = (b["close"] > prior_high) & (b["volume"] > vol_k * vol_avg)
    return entry.to_numpy(), None


def sig_ema(b: pd.DataFrame, fast: int, slow: int, **_) -> tuple:
    f, s = ema(b["close"], fast), ema(b["close"], slow)
    above = f > s
    cross_up = above & ~above.shift(1, fill_value=False)
    return cross_up.to_numpy(), (~above).to_numpy()


def sig_dip(b: pd.DataFrame, look: int, drop: float, **_) -> tuple:
    ret = b["close"] / b["close"].shift(look) - 1
    return (ret <= -drop).to_numpy(), None


def sig_momentum(b: pd.DataFrame, look: int, rise: float, **_) -> tuple:
    ret = b["close"] / b["close"].shift(look) - 1
    return (ret >= rise).to_numpy(), None


STRATEGIES = {
    "Rompimento + volume (5 min)": dict(
        tf=5, fn=sig_breakout,
        grid=dict(n=[12, 24, 48], vol_k=[2.0, 3.0], stop=[0.005, 0.01],
                  target=[0.005, 0.01, 0.02], max_hold=[12, 48])),
    "Cruzamento EMA (15 min)": dict(
        tf=15, fn=sig_ema,
        grid=dict(fast=[4, 8, 12], slow=[24, 48, 96], stop=[0.01, 0.02],
                  target=[None], max_hold=[None])),
    "Reversão após queda (1 min)": dict(
        tf=1, fn=sig_dip,
        grid=dict(look=[5, 15, 30], drop=[0.01, 0.015, 0.02], stop=[0.01, 0.02],
                  target=[0.005, 0.01, 0.02], max_hold=[60, 240])),
    "Momento (15 min)": dict(
        tf=15, fn=sig_momentum,
        grid=dict(look=[4, 8, 16], rise=[0.01, 0.02, 0.03], stop=[0.01, 0.02],
                  target=[None], max_hold=[4, 16])),
}


# ------------------------------------------------------------- execução ----

def split_index(bars: pd.DataFrame, cut: pd.Timestamp) -> int:
    return int(bars.index.searchsorted(cut))


def buy_and_hold(bars: pd.DataFrame, start: int) -> Result:
    o, c, l = bars["open"].to_numpy(), bars["close"].to_numpy(), bars["low"].to_numpy()
    px_in = o[start]
    eq = c[start:] * (1 - COST) / (px_in * (1 + COST))
    worst = l[start:] * (1 - COST) / (px_in * (1 + COST))
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[:-1]
    dd = float((worst / peak - 1).min())
    gross = c[-1] / px_in - 1
    net = eq[-1] - 1
    return Result(1, int(net > 0), gross, net, dd)


def run_symbol(df1: pd.DataFrame) -> tuple[dict, Result, dict]:
    cut = df1.index[0] + pd.Timedelta(days=TRAIN_DAYS)
    out = {}
    for name, spec in STRATEGIES.items():
        bars = resample(df1, spec["tf"])
        k = split_index(bars, cut)
        n = len(bars)
        keys = list(spec["grid"])
        best = None
        n_combos = n_pos = 0
        for combo in itertools.product(*spec["grid"].values()):
            p = dict(zip(keys, combo))
            entry, exit_sig = spec["fn"](bars, **p)
            tr = simulate(bars, entry, exit_sig, p["stop"], p["target"], p["max_hold"], 0, k)
            n_combos += 1
            n_pos += tr.net > 0
            if tr.trades < MIN_TRAIN_TRADES:
                continue
            if best is None or tr.net > best[1].net:
                best = (p, tr)
        if best is None:
            out[name] = dict(params=None, train=None, test=None, share_pos=0.0)
            continue
        p, tr = best
        entry, exit_sig = spec["fn"](bars, **p)
        te = simulate(bars, entry, exit_sig, p["stop"], p["target"], p["max_hold"], k, n)
        out[name] = dict(params=p, train=tr, test=te, share_pos=n_pos / n_combos)
    k1 = split_index(df1, cut)
    bh_test = buy_and_hold(df1, k1)
    info = dict(start=df1.index[0], cut=cut, end=df1.index[-1])
    return out, bh_test, info


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def fmt_params(p: dict | None) -> str:
    if not p:
        return "-"
    return ", ".join(f"{k}={v}" for k, v in p.items() if v is not None)


def main() -> None:
    print("Backtest de sinais rápidos (Binance, 1 minuto)")
    print(f"Custo por lado: {COST * 100:.2f}% (taxa {FEE * 100:.2f}% + derrapagem {SLIPPAGE * 100:.2f}%)")
    print(f"Treino = primeiros {TRAIN_DAYS} dias; prova = o resto (não usado para escolher)\n")
    for sym, file in SYMBOLS.items():
        df1 = load(file)
        res, bh, info = run_symbol(df1)
        days_test = (info["end"] - info["cut"]).total_seconds() / 86400
        print(f"== {sym} ==  treino {info['start']:%Y-%m-%d} a {info['cut']:%Y-%m-%d}, "
              f"prova {info['cut']:%Y-%m-%d} a {info['end']:%Y-%m-%d} ({days_test:.1f} dias)")
        print(f"  Comprar e segurar na prova: {pct(bh.net)} (maior queda {pct(bh.max_dd)})")
        hdr = f"  {'Sinal':30}{'Trades':>7}{'Trades/dia':>11}{'Acerto':>8}{'Sem taxas':>11}{'Com taxas':>11}{'Maior queda':>13}{'Venceu?':>9}{'Lucrou?':>9}{'Treino':>9}{'% ajustes +':>13}"
        print(hdr)
        for name, r in res.items():
            te = r["test"]
            if te is None:
                print(f"  {name:30}  sem ajuste com {MIN_TRAIN_TRADES}+ trades no treino")
                continue
            beat = "SIM" if te.net > bh.net else "NÃO"
            profit = "SIM" if te.net > 0 else "NÃO"
            print(f"  {name:30}{te.trades:>7}{te.trades / days_test:>11.1f}{te.win_rate * 100:>7.0f}%"
                  f"{pct(te.gross):>11}{pct(te.net):>11}{pct(te.max_dd):>13}{beat:>9}{profit:>9}"
                  f"{pct(r['train'].net):>9}{r['share_pos'] * 100:>12.0f}%")
            print(f"  {'':30}ajuste escolhido: {fmt_params(r['params'])}")
        print()
    print("'Venceu?' = ganhou de comprar e segurar. 'Lucrou?' = ganhou de ficar parado em dinheiro (0%).")
    print("'% ajustes +' = quantos ajustes testados deram lucro no treino (baixo = sinal fraco).")
    print("Atenção: 30 dias é pouquíssimo. Passado não garante futuro.")


if __name__ == "__main__":
    main()
