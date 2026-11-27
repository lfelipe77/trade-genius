"""Backtest de ideias de TENDÊNCIA / MOMENTO (BTC e ETH, dados diários).

Pedido do Felipe (2026-11-27): "o número não mexe, muda a estratégia".
O rompimento atual (20/40 dias) fica muito tempo em caixa e o lucro dele no
teste veio de 1-2 operações. Aqui testamos ideias que operam MAIS vezes:

  R  Rompimento curto: fecha acima da máxima de N dias (N=10/20), sai quando
     fecha abaixo da mínima de M dias (M=5/10). Filtro de tendência opcional
     (preço acima da média de F dias, F=0/50/100/200; 0 = sem filtro).
  M  Média: comprado enquanto fecha acima da média de N dias (N=20/50/100).
  X  Cruzamento rápido: média exponencial rápida acima da lenta (10/30, 20/50).
  T  Momento: retorno dos últimos L dias > 0 (L=10/20/30/60).
  C  Rompimento N=10/20 com saída por stop móvel (maior fechamento desde a
     entrada - k x ATR), sem saída por mínima.
  ROT Rotação BTC/ETH: fica no que subiu mais nos últimos L dias, se ele
     subiu; senão, caixa.

Todas têm stop (exigência do Robô de Risco): entrada - k x ATR(14), k=2/3.
Opcional: stop móvel (sobe junto com o preço, nunca desce).

Teste honesto, igual ao backtest_seletivo.py:
  - custo 0,15% por lado (taxa + derrapagem) em toda compra e venda;
  - walk-forward: parâmetros escolhidos só com dados ANTERIORES a cada janela
    de 6 meses (2024-01 até 2026-11); depois roda a janela sem ver o futuro;
  - robustez: % das combinações de parâmetros que lucraram no período de teste;
  - "sem os 2 melhores": retorno do teste tirando as 2 melhores operações.
    Se fica negativo, o lucro dependeu de sorte em 1-2 trades.
  - "na conta": tamanho limitado pela regra de 1% de risco por trade (como o
    Robô de Risco faz no paper). É o que mexeria no número da conta.

Cuidado: 2022-2026 é basicamente UM ciclo de cripto. Passado não garante futuro.

Uso: python backtest_momento.py
"""

from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
TICKERS = ["BTC-USD", "ETH-USD"]
COST = 0.0010 + 0.0005
RISK = 0.01  # regra do Robô de Risco: 1% da conta por trade
TRAIN_START = "2022-06-15"
WINDOWS = [
    ("2024-01-01", "2024-06-30"),
    ("2024-07-01", "2024-12-31"),
    ("2025-01-01", "2025-06-30"),
    ("2025-07-01", "2025-12-31"),
    ("2026-01-01", "2026-12-31"),
]
OOS_START = WINDOWS[0][0]
MIN_TRADES_TRAIN = 5


# ---------------------------------------------------------------- dados
def load(ticker: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{ticker}.csv", parse_dates=["Date"], index_col="Date")
    df = df[["Open", "High", "Low", "Close"]].dropna().iloc[:-1]  # hoje incompleto
    c = df.Close
    prev = c.shift(1)
    tr = pd.concat([df.High - df.Low, (df.High - prev).abs(), (df.Low - prev).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    return df


def sma(c, n):
    return c.rolling(n).mean()


# ---------------------------------------------------------------- regras
def rules(df: pd.DataFrame, kind: str, p: dict):
    """Devolve (entrada, saída) booleanas, calculadas no fechamento do dia."""
    c = df.Close
    filt = (c > sma(c, p["f"])) if p.get("f") else pd.Series(True, df.index)
    if kind in ("R", "C"):
        entry = (c > df.High.rolling(p["n"]).max().shift(1)) & filt
        exit_ = (c < df.Low.rolling(p["m"]).min().shift(1)) if kind == "R" else pd.Series(False, df.index)
    elif kind == "M":
        entry = c > sma(c, p["n"])
        exit_ = ~entry
    elif kind == "X":
        up = c.ewm(span=p["a"], adjust=False).mean() > c.ewm(span=p["b"], adjust=False).mean()
        entry, exit_ = up & filt, ~up
    elif kind == "T":
        up = c.pct_change(p["l"]) > 0
        entry, exit_ = up & filt, ~up
    else:
        raise ValueError(kind)
    return entry.fillna(False).values, exit_.fillna(False).values


def simulate(df: pd.DataFrame, kind: str, p: dict):
    """Um ativo. Devolve (ret 100% investido, ret na conta c/ regra 1%, posição, trades)."""
    entry, exit_ = rules(df, kind, p)
    o, h, lo, c, atr = (df[k].values for k in ("Open", "High", "Low", "Close", "atr"))
    n = len(df)
    ret = np.zeros(n)
    w = np.zeros(n)  # peso na conta (regra 1%)
    pos = np.zeros(n)
    trades = []
    inside, ep, stop, top, edate, wt = False, 0.0, 0.0, 0.0, None, 0.0
    for i in range(1, n):
        if inside:
            if lo[i] <= stop:
                px = min(o[i], stop)
                ret[i] = px / c[i - 1] - 1 - COST
                w[i] = wt
                trades.append((edate, df.index[i], px / ep - 1 - 2 * COST, wt))
                inside = False
                continue  # não recompra no mesmo dia
            ret[i] = c[i] / c[i - 1] - 1
            w[i] = wt
            if exit_[i]:
                ret[i] -= COST
                trades.append((edate, df.index[i], c[i] / ep - 1 - 2 * COST, wt))
                inside = False
            elif p.get("trail"):
                top = max(top, c[i])
                stop = max(stop, top - p["k"] * atr[i])
        elif entry[i] and not np.isnan(atr[i]):
            inside, ep, top, edate = True, c[i], c[i], df.index[i]
            stop = c[i] - p["k"] * atr[i]
            dist = (c[i] - stop) / c[i] + 2 * COST
            wt = min(1.0, RISK / dist)
            ret[i] = -COST
            w[i] = wt
        pos[i] = 1.0 if inside else 0.0
    r = pd.Series(ret, df.index)
    return r, r * pd.Series(w, df.index), pd.Series(pos, df.index), trades


def grid(kind: str):
    ks, trails = [2, 3], [0, 1]
    if kind == "R":
        for n, m, f, k, t in product([10, 20], [5, 10], [0, 50, 100, 200], ks, trails):
            if m < n:
                yield {"n": n, "m": m, "f": f, "k": k, "trail": t}
    elif kind == "C":
        for n, f, k in product([10, 20], [0, 50, 100, 200], [2, 3, 4]):
            yield {"n": n, "f": f, "k": k, "trail": 1}
    elif kind == "M":
        for n, k, t in product([20, 50, 100], ks, trails):
            yield {"n": n, "k": k, "trail": t}
    elif kind == "X":
        for (a, b), f, k, t in product([(10, 30), (20, 50)], [0, 200], ks, trails):
            yield {"a": a, "b": b, "f": f, "k": k, "trail": t}
    elif kind == "T":
        for l, f, k, t in product([10, 20, 30, 60], [0, 200], ks, trails):
            yield {"l": l, "f": f, "k": k, "trail": t}


# ---------------------------------------------------------------- rotação
def rotation(dfs: dict, p: dict):
    """Fica no ativo com maior retorno de L dias, se > 0. Stop k x ATR."""
    idx = dfs["BTC-USD"].index.intersection(dfs["ETH-USD"].index)
    d = {t: dfs[t].loc[idx] for t in TICKERS}
    mom = pd.DataFrame({t: d[t].Close.pct_change(p["l"]) for t in TICKERS})
    n = len(idx)
    ret, retw, pos = np.zeros(n), np.zeros(n), np.zeros(n)
    trades = []
    cur, ep, stop, top, edate, wt = None, 0.0, 0.0, 0.0, None, 0.0
    for i in range(1, n):
        if cur is not None:
            x = d[cur]
            o, lo, c, cp, a = x.Open.iat[i], x.Low.iat[i], x.Close.iat[i], x.Close.iat[i - 1], x.atr.iat[i]
            if lo <= stop:
                px = min(o, stop)
                ret[i] = px / cp - 1 - COST
                retw[i] = ret[i] * wt
                trades.append((edate, idx[i], px / ep - 1 - 2 * COST, wt))
                cur = None
                continue
            ret[i] = c / cp - 1
            m = mom.iloc[i]
            best = m.idxmax() if m.notna().all() else None
            if best is None or m[best] <= 0 or best != cur:
                ret[i] -= COST
                retw[i] = ret[i] * wt
                trades.append((edate, idx[i], c / ep - 1 - 2 * COST, wt))
                cur = None
                pos[i] = 0
                # troca no mesmo dia, se o outro está melhor e subindo
                if best is not None and m[best] > 0 and not np.isnan(d[best].atr.iat[i]):
                    cur = best
                else:
                    continue
            else:
                retw[i] = ret[i] * wt
                if p.get("trail"):
                    top = max(top, c)
                    stop = max(stop, top - p["k"] * a)
                pos[i] = 1
                continue
        else:
            m = mom.iloc[i]
            if not m.notna().all():
                continue
            best = m.idxmax()
            if m[best] <= 0 or np.isnan(d[best].atr.iat[i]):
                continue
            cur = best
        x = d[cur]
        c, a = x.Close.iat[i], x.atr.iat[i]
        ep, top, edate = c, c, idx[i]
        stop = c - p["k"] * a
        wt = min(1.0, RISK / ((c - stop) / c + 2 * COST))
        ret[i] -= COST
        retw[i] += -COST * wt
        pos[i] = 1
    r = pd.Series(ret, idx)
    return r, pd.Series(retw, idx), pd.Series(pos, idx), trades


def rot_grid():
    for l, k, t in product([10, 20, 30, 60], [2, 3], [0, 1]):
        yield {"l": l, "k": k, "trail": t}


# ---------------------------------------------------------------- métricas
def max_dd(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min())


def walk_forward(sims: list, params: list):
    """sims: lista de (ret, retw, pos, trades). Escolhe por retorno no treino."""
    out_r, out_w, out_pos, out_tr, chosen = [], [], [], [], []
    for start, end in WINDOWS:
        best, best_score = None, -np.inf
        for j, (r, _, _, tr) in enumerate(sims):
            ntr = sum(1 for t in tr if TRAIN_START <= str(t[1].date()) < start)
            if ntr < MIN_TRADES_TRAIN:
                continue
            score = (1 + r.loc[TRAIN_START:start].iloc[:-1]).prod()
            if score > best_score:
                best, best_score = j, score
        if best is None:
            continue
        r, rw, pos, tr = sims[best]
        out_r.append(r.loc[start:end])
        out_w.append(rw.loc[start:end])
        out_pos.append(pos.loc[start:end])
        out_tr += [t for t in tr if start <= str(t[0].date()) <= end]
        chosen.append((start, params[best], best_score - 1))
    ret, retw, pos = pd.concat(out_r), pd.concat(out_w), pd.concat(out_pos)
    eq, eqw = (1 + ret).cumprod(), (1 + retw).cumprod()
    gains = sorted((t[2] for t in out_tr), reverse=True)
    sem2 = float(np.prod([1 + g for g in gains[2:]]) - 1) if gains else 0.0
    return {
        "ret": eq.iloc[-1] - 1, "dd": max_dd(eq),
        "conta": eqw.iloc[-1] - 1, "dd_conta": max_dd(eqw),
        "trades": len(out_tr), "wins": sum(1 for g in gains if g > 0),
        "sem2": sem2, "time_in": float(pos.mean()),
        "pos_windows": sum(1 for s, e in WINDOWS if (1 + ret.loc[s:e]).prod() > 1),
        "chosen": chosen, "retw": retw, "trade_list": out_tr,
    }


def robustness(sims: list):
    outs = np.array([(1 + r.loc[OOS_START:]).prod() - 1 for r, _, _, _ in sims])
    return float((outs > 0).mean()), float(np.median(outs))


def buy_hold(df: pd.DataFrame):
    c = df.Close.loc[OOS_START:]
    r = c.pct_change().fillna(0)
    r.iloc[0] -= COST
    eq = (1 + r).cumprod()
    return eq.iloc[-1] - 1, max_dd(eq)


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


NAMES = {"R": "R Rompimento curto", "C": "C Romp.+stop móvel", "M": "M Acima da média",
         "X": "X Cruzamento rápido", "T": "T Momento L dias"}


def run_all():
    dfs = {t: load(t) for t in TICKERS}
    res = {}
    for t in TICKERS:
        for kind in NAMES:
            params = list(grid(kind))
            sims = [simulate(dfs[t], kind, p) for p in params]
            r = walk_forward(sims, params)
            r["rob"], r["med"] = robustness(sims)
            res[(t, kind)] = r
    params = list(rot_grid())
    sims = [rotation(dfs, p) for p in params]
    r = walk_forward(sims, params)
    r["rob"], r["med"] = robustness(sims)
    res[("BTC+ETH", "ROT")] = r
    return dfs, res


def linha(nome, r):
    print(f"  {nome:22}{r['trades']:>6}{r['wins']:>7}{pct(r['ret']):>9}{pct(r['dd']):>9}"
          f"{pct(r['sem2']):>10}{r['time_in'] * 100:>7.0f}%{r['pos_windows']:>5}/5"
          f"{r['rob'] * 100:>8.0f}%{pct(r['conta']):>9}")


def main() -> None:
    dfs, res = run_all()
    print("Tendência/momento: walk-forward, custo 0,15% por lado, teste fora da amostra 2024-01 a 2026-11\n")
    cab = (f"  {'Estratégia':22}{'Oper':>6}{'Acert':>7}{'Ret':>9}{'Queda':>9}{'Sem 2+':>10}"
           f"{'Tempo':>8}{'Jan+':>7}{'Robust':>9}{'NaConta':>9}")
    for t in TICKERS:
        bh, bh_dd = buy_hold(dfs[t])
        print(f"== {t} ==")
        print(cab)
        for kind, nome in NAMES.items():
            linha(nome, res[(t, kind)])
        print(f"  {'Comprar e segurar':22}{1:>6}{'':>7}{pct(bh):>9}{pct(bh_dd):>9}\n")
    print("== Rotação BTC/ETH (um só bolo) ==")
    print(cab)
    linha("ROT Rotação", res[("BTC+ETH", "ROT")])
    print("\nColunas: Ret = 100% investido; Sem 2+ = tirando as 2 melhores operações;")
    print("Jan+ = janelas de 6 meses no lucro; Robust = % de combinações que lucraram no teste;")
    print("NaConta = efeito na conta com a regra de 1% de risco por operação.\n")
    for key, r in res.items():
        print(f"{key}: " + "; ".join(f"{s[:7]} {p}" for s, p, _ in r["chosen"]))
    print("\nAtenção: um só ciclo de cripto. Passado não garante futuro.")


if __name__ == "__main__":
    main()
