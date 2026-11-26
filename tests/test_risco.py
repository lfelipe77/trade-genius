"""Testes do Robô de Risco. Rodar: python -m unittest -v"""

import tempfile
import unittest
from pathlib import Path

from risco import Conta, Ordem, carregar_config, checar_ordem, tamanho_maximo

CFG = {
    "risco_max_por_trade": 0.01,
    "perda_max_diaria": 0.03,
    "custo_por_operacao": 0.0015,
    "parar_tudo": False,
    "arquivo_parar": "PARAR",
    "ativos_permitidos": ["BTC-USD", "ETH-USD"],
}


class TestRisco(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)  # pasta vazia: sem arquivo PARAR
        self.conta = Conta(patrimonio=10_000, patrimonio_inicio_dia=10_000, caixa=10_000)

    def tearDown(self):
        self.tmp.cleanup()

    def checar(self, ordem, conta=None, cfg=None):
        return checar_ordem(ordem, conta or self.conta, cfg or CFG, pasta=self.pasta)

    def compra_ok(self):
        # risco = 0.02 x 4500 = 90 + custos ~5,26 = ~95 < 100 (1% de 10.000)
        return Ordem("BTC-USD", "buy", 0.02, 90_000, stop=85_500)

    def test_compra_dentro_das_regras_aprovada(self):
        self.assertTrue(self.checar(self.compra_ok()).aprovada)

    def test_risco_acima_de_1_por_cento_vetado(self):
        d = self.checar(Ordem("BTC-USD", "buy", 0.03, 90_000, stop=85_500))  # ~$143
        self.assertFalse(d.aprovada)
        self.assertIn("máximo por trade", d.motivo)

    def test_custos_contam_no_risco(self):
        # sem custos seria exatamente $100 (no limite); com custos passa
        d = self.checar(Ordem("BTC-USD", "buy", 0.1, 10_000, stop=9_000))
        self.assertFalse(d.aprovada)

    def test_compra_sem_stop_vetada(self):
        d = self.checar(Ordem("BTC-USD", "buy", 0.001, 90_000))
        self.assertFalse(d.aprovada)
        self.assertIn("sem stop", d.motivo)

    def test_stop_acima_do_preco_vetado(self):
        self.assertFalse(self.checar(Ordem("BTC-USD", "buy", 0.001, 90_000, stop=95_000)).aprovada)

    def test_botao_parar_por_arquivo(self):
        (self.pasta / "PARAR").write_text("")
        d = self.checar(self.compra_ok())
        self.assertFalse(d.aprovada)
        self.assertIn("parar", d.motivo)

    def test_botao_parar_bloqueia_venda_tambem(self):
        (self.pasta / "PARAR").write_text("")
        conta = Conta(10_000, 10_000, 5_000, {"BTC-USD": 0.05})
        self.assertFalse(self.checar(Ordem("BTC-USD", "sell", 0.05, 90_000), conta).aprovada)

    def test_botao_parar_por_config(self):
        cfg = dict(CFG, parar_tudo=True)
        self.assertFalse(self.checar(self.compra_ok(), cfg=cfg).aprovada)

    def test_limite_diario_batido_veta_compra(self):
        conta = Conta(patrimonio=9_700, patrimonio_inicio_dia=10_000, caixa=9_700)  # -3%
        d = self.checar(self.compra_ok(), conta)
        self.assertFalse(d.aprovada)
        self.assertIn("limite diário", d.motivo)

    def test_compra_que_pode_passar_do_limite_diario_vetada(self):
        conta = Conta(patrimonio=9_750, patrimonio_inicio_dia=10_000, caixa=9_750)  # -2,5%
        d = self.checar(self.compra_ok(), conta)  # 250 + 95 > 300
        self.assertFalse(d.aprovada)
        self.assertIn("der errado", d.motivo)

    def test_venda_liberada_com_limite_diario_batido(self):
        conta = Conta(9_600, 10_000, 5_000, {"BTC-USD": 0.05})
        self.assertTrue(self.checar(Ordem("BTC-USD", "sell", 0.05, 90_000), conta).aprovada)

    def test_venda_a_descoberto_vetada(self):
        d = self.checar(Ordem("ETH-USD", "sell", 1.0, 3_000))
        self.assertFalse(d.aprovada)
        self.assertIn("descoberto", d.motivo)

    def test_sem_alavancagem(self):
        conta = Conta(10_000, 10_000, caixa=1_000)
        d = self.checar(self.compra_ok(), conta)  # custa $1.800
        self.assertFalse(d.aprovada)
        self.assertIn("caixa", d.motivo)

    def test_ativo_nao_permitido(self):
        self.assertFalse(self.checar(Ordem("DOGE-USD", "buy", 1, 0.1, stop=0.09)).aprovada)

    def test_lado_invalido(self):
        self.assertFalse(self.checar(Ordem("BTC-USD", "short", 0.01, 90_000, stop=85_000)).aprovada)

    def test_quantidade_zero_ou_negativa(self):
        self.assertFalse(self.checar(Ordem("BTC-USD", "buy", 0, 90_000, stop=85_000)).aprovada)
        self.assertFalse(self.checar(Ordem("BTC-USD", "buy", -1, 90_000, stop=85_000)).aprovada)

    def test_tamanho_maximo_passa_no_limite(self):
        q = tamanho_maximo(90_000, 85_500, self.conta, CFG)
        self.assertTrue(self.checar(Ordem("BTC-USD", "buy", q * 0.999, 90_000, stop=85_500)).aprovada)
        self.assertFalse(self.checar(Ordem("BTC-USD", "buy", q * 1.01, 90_000, stop=85_500)).aprovada)

    def test_config_do_repositorio_carrega(self):
        cfg = carregar_config()
        self.assertEqual(cfg["risco_max_por_trade"], 0.01)
        self.assertFalse(cfg["parar_tudo"])


if __name__ == "__main__":
    unittest.main()
