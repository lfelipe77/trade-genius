import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import execucao
import relatorio


def barras(precos):
    return [{"c": p} for p in precos]


class FakeAlpaca:
    """Corretora de mentira: nada sai do computador."""
    ErroAlpaca = execucao.alpaca.ErroAlpaca

    def __init__(self, precos, posicoes=None, equity=100_000, last=100_000, cash=100_000):
        self.precos, self.pos = precos, posicoes or []
        self.c = {"equity": str(equity), "last_equity": str(last), "cash": str(cash), "status": "ACTIVE"}
        self.enviadas = []

    def conta(self): return self.c
    def posicoes(self): return self.pos
    def barras_diarias(self, simbolo, dias=0): return barras(self.precos[simbolo])
    def enviar_ordem_mercado(self, simbolo, lado, q):
        self.enviadas.append((simbolo, lado, q))
        return {"id": "x", "status": "accepted"}


SUBINDO = [100 + i for i in range(260)]   # média 50 > 200
CAINDO = [400 - i for i in range(260)]    # média 50 < 200


class TestExecucao(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(execucao, "LOGS", self.tmp / "logs"),
                  mock.patch.object(execucao, "ESTADO", self.tmp / "estado.json")]
        for x in self.p: x.start()

    def tearDown(self):
        for x in self.p: x.stop()

    def eventos(self):
        f = next((self.tmp / "logs").glob("*.jsonl"))
        return [json.loads(l) for l in f.read_text().splitlines()]

    def rodar(self, fake, **kw):
        with mock.patch.object(execucao, "alpaca", fake):
            execucao.rodar(**kw)

    def test_sinal(self):
        self.assertEqual(execucao.sinal(SUBINDO), "comprado")
        self.assertEqual(execucao.sinal(CAINDO), "caixa")
        self.assertIsNone(execucao.sinal(SUBINDO[:150]))

    def test_compra_respeita_1_porcento(self):
        fake = FakeAlpaca({"BTC/USD": SUBINDO, "ETH/USD": CAINDO})
        self.rodar(fake)
        self.assertEqual(len(fake.enviadas), 1)
        simbolo, lado, q = fake.enviadas[0]
        self.assertEqual((simbolo, lado), ("BTC/USD", "buy"))
        preco = SUBINDO[-1]
        risco = q * preco * execucao.STOP_PCT
        self.assertLessEqual(risco, 1000)  # 1% de 100 mil
        est = json.loads((self.tmp / "estado.json").read_text())
        self.assertAlmostEqual(est["BTC-USD"]["stop"], round(preco * 0.95, 2))

    def test_simular_nao_envia(self):
        fake = FakeAlpaca({"BTC/USD": SUBINDO, "ETH/USD": SUBINDO})
        self.rodar(fake, simular=True)
        self.assertEqual(fake.enviadas, [])
        self.assertEqual(sum(e["tipo"] == "simulada" for e in self.eventos()), 2)

    def test_limite_diario_veta_compra(self):
        fake = FakeAlpaca({"BTC/USD": SUBINDO, "ETH/USD": CAINDO}, equity=96_000, last=100_000, cash=96_000)
        self.rodar(fake)
        self.assertEqual(fake.enviadas, [])
        self.assertTrue(any(e["tipo"] == "veto" for e in self.eventos()))

    def test_vende_quando_sinal_vira(self):
        pos = [{"symbol": "ETHUSD", "qty": "2.5"}]
        fake = FakeAlpaca({"BTC/USD": CAINDO, "ETH/USD": CAINDO}, posicoes=pos)
        self.rodar(fake)
        self.assertEqual(fake.enviadas, [("ETH/USD", "sell", 2.5)])

    def test_vende_no_stop(self):
        (self.tmp / "estado.json").write_text(json.dumps({"BTC-USD": {"stop": 400}}))
        pos = [{"symbol": "BTCUSD", "qty": "1"}]
        fake = FakeAlpaca({"BTC/USD": SUBINDO, "ETH/USD": CAINDO}, posicoes=pos)
        self.rodar(fake)
        self.assertEqual(fake.enviadas, [("BTC/USD", "sell", 1.0)])

    def test_parar_bloqueia_tudo(self):
        with mock.patch("risco.parar_ligado", return_value=True):
            fake = FakeAlpaca({"BTC/USD": SUBINDO, "ETH/USD": SUBINDO})
            self.rodar(fake)
        self.assertEqual(fake.enviadas, [])

    def test_relatorio(self):
        fake = FakeAlpaca({"BTC/USD": SUBINDO, "ETH/USD": CAINDO}, equity=96_000, last=100_000, cash=96_000)
        self.rodar(fake)
        dia = next((self.tmp / "logs").glob("*.jsonl")).stem
        with mock.patch.object(relatorio, "PASTA", self.tmp):
            txt = relatorio.gerar(dia)
        self.assertIn("Vetos do Robô de Risco (1)", txt)
        self.assertIn("$96.000,00", txt)


class TestSoPaper(unittest.TestCase):
    def test_bloqueia_conta_real(self):
        with self.assertRaises(execucao.alpaca.ErroAlpaca):
            execucao.alpaca._pedir("GET", "https://api.alpaca.markets/v2/account")


if __name__ == "__main__":
    unittest.main()
