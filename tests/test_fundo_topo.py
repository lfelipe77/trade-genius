import unittest

import pandas as pd

from backtest_fundo_topo import simulate


def bars(closes):
    # open = fechamento anterior; high/low = extremos simples
    rows, prev = [], closes[0]
    for c in closes:
        rows.append([prev, max(prev, c), min(prev, c), c])
        prev = c
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


class TestFundoTopo(unittest.TestCase):
    def test_compra_depois_de_3_quedas_e_vende_na_primeira_queda(self):
        # 3 quedas, sobe (sinal), compra no abrir seguinte (100.5), sobe, cai (sinal), vende
        b = bars([103, 102, 101, 100, 100.5, 101.5, 102.5, 102, 102])
        r = simulate(b, n_down=3, k_exit=1, start=0, end=len(b), stop=0.5)
        self.assertEqual(r.trades, 1)
        self.assertAlmostEqual(r.gross, 102 / 100.5 - 1)
        self.assertLess(r.net, r.gross)

    def test_sem_quedas_suficientes_nao_compra(self):
        b = bars([103, 102, 101, 101.5, 102, 101, 102])
        r = simulate(b, n_down=3, k_exit=1, start=0, end=len(b))
        self.assertEqual(r.trades, 0)

    def test_k2_ignora_uma_queda_so(self):
        b = bars([103, 102, 101, 100, 100.5, 101, 100.8, 102, 101.5, 101, 101])
        r1 = simulate(b, 3, 1, 0, len(b), stop=0.5)
        r2 = simulate(b, 3, 2, 0, len(b), stop=0.5)
        self.assertAlmostEqual(r1.gross, 100.8 / 100.5 - 1)  # vende no abrir após a 1a queda
        self.assertAlmostEqual(r2.gross, 101 / 100.5 - 1)    # vende só após 2 quedas seguidas


if __name__ == "__main__":
    unittest.main()
