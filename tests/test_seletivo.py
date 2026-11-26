"""Testes do backtest seletivo: sem olhar o futuro e custos cobrados."""

import unittest

import backtest_seletivo as b


class TestSeletivo(unittest.TestCase):

    def test_sem_olhar_o_futuro(self):
        """Mudar os preços do futuro não pode mudar as decisões do passado."""
        df = b.load("BTC-USD")
        cut = df.index[1000]
        p = {"n": 20, "m": 10, "vol": 1, "k": 2, "g": 80}
        _, pos_full, _ = b.simulate(df, "B", p)
        self.assertGreater(pos_full.loc[:cut].sum(), 0)
        _, pos_cut, _ = b.simulate(b.add_indicators(df.loc[:cut]), "B", p)
        assert (pos_full.loc[:cut] == pos_cut).all()

    def test_cada_trade_paga_ida_e_volta(self):
        df = b.load("ETH-USD")
        _, _, trades = b.simulate(df, "A", {"t": 50, "x": 30, "k": 2, "g": 101})
        self.assertTrue(trades)
        for entrada, saida, r in trades:
            px_in = df.Close.loc[entrada]
            # retorno do trade é sempre menor que o movimento bruto máximo possível
            assert r <= df.High.loc[entrada:saida].max() / px_in - 1 - 2 * b.COST + 1e-12

    def test_fear_greed_carregado(self):
        df = b.load("BTC-USD")
        assert df.fng.loc["2022-06-15":].notna().all()
