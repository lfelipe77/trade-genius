"""Backtest da regra do Felipe: "comprar no fundo, vender no topo".

A regra (em palavras do Felipe):
  - Espera o preço cair VÁRIAS velas seguidas (N = 3 a 7 velas para baixo).
  - Na PRIMEIRA vela que sobe depois disso -> COMPRA.
  - Segura enquanto sobe (sobe, desce, sobe... tudo bem).
  - Quando cair K velas seguidas (K = 1 ou 2) -> VENDE.
  - Espera a próxima queda e repete.

Vela "para baixo" = fechou abaixo do fechamento anterior. "Para cima" = acima.
Tem também um stop de segurança de 2% (o Robô de Risco exige stop em toda compra).

Como é honesto (walk-forward), igual ao backtest_minuto.py:
  - Dias 1-20 (treino): testamos todos os ajustes (N, K, vela de 1/5/15 min)
    e escolhemos o melhor pelo retorno no treino.
  - Dias 21-30 (prova): rodamos SÓ o escolhido, em dias que não foram usados.
  - Sinal no fechamento da vela; ordem no ABRIR da vela seguinte
    (ninguém sabe que foi o fundo antes da vela fechar).
  - Custos por lado: taxa Binance 0,10% + derrapagem 0,03%.

Dados de segundos (os "pontinhos" de 1-3 s) não existem de graça; usamos 1 min
e velas de 5 e 15 min montadas a partir dele.

Só pesquisa: NÃO envia ordens. Uso: python backtest_fundo_topo.py
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from backtest_minuto import COST, SYMBOLS, TRAIN_DAYS, Result, load, resample

TIMEFRAMES = (1, 5, 15)
N_DOWN = (3, 4, 5, 6, 7)     # velas para baixo antes de comprar
K_EXIT = (1, 2)              # velas para baixo para vender
STOP = 0.02                  # stop de segurança
MIN_TRAIN_TRADES = 5


def simulate(bars: pd.DataFrame, n_down: int, k_exit: int, start: int, end: int,
             stop: float = STOP) -> Result:
    """Uma posição por vez, 100% do capital, entre as velas [start, end)."""
    o, l, c = (bars[k].to_numpy() for k in ("open", "low", "close"))
    eq_g = eq_n = peak = 1.0
    max_dd = 0.0
    trades = wins = 0
    downs = 0             # velas para baixo seguidas (antes da compra)
    in_pos = False
    entry = stop_px = 0.0
    exit_downs = 0        # velas para baixo seguidas (depois da compra)
    pending: str | None = None  # "buy" / "sell" no abrir desta vela

    def close_trade(px: float) -> None:
        nonlocal eq_g, eq_n, trades, wins, in_pos, peak, max_dd
        r = px / entry
        eq_g *= r
        eq_n *= r * (1 - COST) / (1 + COST)
        trades += 1
        wins += r * (1 - COST) / (1 + COST) > 1
        in_pos = False
        peak = max(peak, eq_n)
        max_dd = min(max_dd, eq_n / peak - 1)

    for i in range(max(start, 1), end):
        if pending == "buy" and not in_pos:
            in_pos, entry, stop_px, exit_downs = True, o[i], o[i] * (1 - stop), 0
        elif pending == "sell" and in_pos:
            close_trade(o[i])
        pending = None

        if in_pos and l[i] <= stop_px:           # stop tocado dentro da vela
            close_trade(min(stop_px, o[i]))
            downs = 0
            continue

        down, up = c[i] < c[i - 1], c[i] > c[i - 1]
        if in_pos:
            exit_downs = exit_downs + 1 if down else 0
            if exit_downs >= k_exit:
                pending = "sell"
                downs = exit_downs            # a queda pode virar o próximo fundo
            # drawdown com a posição aberta
            mark = eq_n * (c[i] / entry) * (1 - COST) / (1 + COST)
            max_dd = min(max_dd, mark / peak - 1)
        else:
            if up and downs >= n_down:
                pending = "buy"
            downs = downs + 1 if down else 0

    if in_pos:                                    # fecha no fim do período
        close_trade(c[end - 1])
    return Result(trades, wins, eq_g - 1, eq_n - 1, max_dd)


def buy_and_hold(bars: pd.DataFrame, start: int) -> float:
    c = bars["close"].to_numpy()
    return c[-1] / bars["open"].to_numpy()[start] * (1 - COST) / (1 + COST) - 1


def run_symbol(df1: pd.DataFrame) -> dict:
    cut = df1.index[0] + pd.Timedelta(days=TRAIN_DAYS)
    rows = []
    for tf, n, k in itertools.product(TIMEFRAMES, N_DOWN, K_EXIT):
        b = resample(df1, tf)
        s = int(np.searchsorted(b.index, cut))
        tr, te = simulate(b, n, k, 0, s), simulate(b, n, k, s, len(b))
        rows.append(dict(tf=tf, n=n, k=k, train=tr, test=te))
    ok = [r for r in rows if r["train"].trades >= MIN_TRAIN_TRADES]
    best = max(ok, key=lambda r: r["train"].net)
    b1 = resample(df1, 1)
    bh = buy_and_hold(b1, int(np.searchsorted(b1.index, cut)))
    return dict(rows=rows, best=best, bh=bh)


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def main() -> None:
    print("Regra 'fundo/topo' - walk-forward 20d treino / 10d prova, custo 0,13%/lado\n")
    for name, file in SYMBOLS.items():
        res = run_symbol(load(file))
        rows, best = res["rows"], res["best"]
        tr, te = best["train"], best["test"]
        pos_train = sum(r["train"].net > 0 for r in rows)
        pos_test = sum(r["test"].net > 0 for r in rows)
        print(f"== {name} ==")
        print(f"Escolhido no treino: vela {best['tf']} min, {best['n']} velas p/ baixo, "
              f"vende após {best['k']} queda(s)")
        print(f"  Treino: {tr.trades} trades, acerto {tr.win_rate:.0%}, líquido {pct(tr.net)}")
        print(f"  PROVA : {te.trades} trades, acerto {te.win_rate:.0%}, "
              f"sem taxa {pct(te.gross)}, líquido {pct(te.net)}, maior queda {pct(te.max_dd)}")
        print(f"  Comprar e segurar (prova): {pct(res['bh'])} | Ficar parado: +0.0%")
        print(f"  Ajustes com lucro: treino {pos_train}/{len(rows)}, prova {pos_test}/{len(rows)}")
        print("  Todos os ajustes (prova, líquido / trades):")
        for tf in TIMEFRAMES:
            cells = [f"N{r['n']}K{r['k']} {pct(r['test'].net)}/{r['test'].trades}"
                     for r in rows if r["tf"] == tf]
            print(f"    {tf:>2} min: " + "  ".join(cells))
        print()


if __name__ == "__main__":
    main()
