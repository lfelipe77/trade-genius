import unittest

import numpy as np
import pandas as pd

from backtest_minuto import COST, simulate


def bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


class TestSimulador(unittest.TestCase):
    def test_stop_perde_stop_mais_custos(self):
        b = bars([[100, 100, 100, 100], [100, 101, 98, 99], [99, 99, 99, 99]])
        r = simulate(b, np.array([True, False, False]), None, stop=0.01, target=0.05,
                     max_hold=None, start=0, end=3)
        self.assertEqual((r.trades, r.wins), (1, 0))
        self.assertAlmostEqual(r.gross, -0.01)
        self.assertAlmostEqual(r.net, 99 * (1 - COST) / (100 * (1 + COST)) - 1)

    def test_alvo_e_entrada_no_proximo_abrir(self):
        b = bars([[100, 100, 100, 100], [102, 102, 102, 102], [102, 104, 101.5, 103]])
        r = simulate(b, np.array([True, False, False]), None, stop=0.01, target=0.01,
                     max_hold=None, start=0, end=3)
        self.assertEqual((r.trades, r.wins), (1, 1))
        self.assertAlmostEqual(r.gross, 0.01)

    def test_sem_sinal_sem_trade(self):
        b = bars([[100, 100, 100, 100]] * 3)
        r = simulate(b, np.zeros(3, bool), None, 0.01, None, None, 0, 3)
        self.assertEqual((r.trades, r.net), (0, 0))


if __name__ == "__main__":
    unittest.main()
