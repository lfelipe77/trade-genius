import numpy as np
import pandas as pd

from backtest_minuto import COST, simulate


def bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_stop_hit_loses_stop_plus_costs():
    b = bars([[100, 100, 100, 100], [100, 101, 98, 99], [99, 99, 99, 99]])
    entry = np.array([True, False, False])
    r = simulate(b, entry, None, stop=0.01, target=0.05, max_hold=None, start=0, end=3)
    assert r.trades == 1 and r.wins == 0
    assert abs(r.gross - (-0.01)) < 1e-9
    assert abs(r.net - (99 * (1 - COST) / (100 * (1 + COST)) - 1)) < 1e-9


def test_target_hit_and_entry_next_open():
    b = bars([[100, 100, 100, 100], [102, 102, 102, 102], [102, 104, 101.5, 103]])
    entry = np.array([True, False, False])
    r = simulate(b, entry, None, stop=0.01, target=0.01, max_hold=None, start=0, end=3)
    # entra no abrir da barra 1 (102), alvo 103.02
    assert r.trades == 1 and r.wins == 1
    assert abs(r.gross - 0.01) < 1e-9


def test_no_signal_no_trade():
    b = bars([[100, 100, 100, 100]] * 3)
    r = simulate(b, np.zeros(3, bool), None, 0.01, None, None, 0, 3)
    assert r.trades == 0 and r.net == 0
