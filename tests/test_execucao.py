import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import execucao
import relatorio
import sinais


def velas(precos):
    """Velas diárias de mentira: máxima +1%, mínima -1%."""
    out, ant = [], precos[0]
    for i, c in enumerate(precos):
        out.append({"t": f"2026-{i:04d}", "o": ant, "h": c * 1.01, "l": c * 0.99, "c": c})
        ant = c
    return out


PLANO = [100.0] * 300
ROMPEU_HOJE = PLANO + [120.0]          # último dia completo rompeu
ROMPEU_ANTES = PLANO + [120.0, 121.0]  # rompeu, mas foi ontem (sinal antigo)
CAINDO = [400.0 - i for i in range(300)]


class TestRompimento(unittest.TestCase):
    def test_rompeu_hoje_pode_comprar(self):
        s = sinais.rompimento(velas(ROMPEU_HOJE), 120.0, n=20, m=10, k=2)
        self.assertEqual(s.quer, "comprado")
        self.assertTrue(s.pode_comprar)
        self.assertLess(s.stop, 120.0)

    def test_sinal_antigo_nao_entra_atrasado(self):
        s = sinais.rompimento(velas(ROMPEU_ANTES), 121.0, n=20, m=10, k=2)
        self.assertEqual(s.quer, "comprado")
        self.assertFalse(s.pode_comprar)

    def test_caindo_quer_caixa(self):
        s = sinais.rompimento(velas(CAINDO), 101.0, n=20, m=10, k=2)
        self.assertEqual(s.quer, "caixa")

    def test_sai_quando_fecha_abaixo_da_minima(self):
        s = sinais.rompimento(velas(ROMPEU_HOJE + [121, 122, 90]), 90.0, n=20, m=10, k=2)
        self.assertEqual(s.quer, "caixa")

    def test_poucos_dados(self):
        self.assertEqual(sinais.rompimento(velas(PLANO[:100]), 100.0).quer, "caixa")

    def test_medias_continua_funcionando(self):
        self.assertEqual(sinais.medias(velas([100 + i for i in range(260)]), 360).quer, "comprado")


class TestRecuo(unittest.TestCase):
    def test_desligada_por_padrao(self):
        self.assertNotIn("recuo", [nome for nome, _ in sinais.USAR.values()])

    def test_compra_queda_forte_em_alta(self):
        precos = [100 + i * 0.5 for i in range(200)] + [185]  # alta e depois queda forte
        s = sinais.recuo(velas(precos), 185.0, t=100, x=20, k=2)
        self.assertEqual(s.quer, "comprado")
        self.assertTrue(s.pode_comprar)

    def test_sem_tendencia_nao_compra(self):
        s = sinais.recuo(velas(CAINDO), 101.0, t=100, x=20, k=2)
        self.assertEqual(s.quer, "caixa")

    def test_bate_com_o_backtest(self):
        try:
            import backtest_seletivo as b
        except ImportError:
            self.skipTest("pandas não instalado")
        for ativo in ("BTC-USD", "ETH-USD"):
            df = b.load(ativo)
            for kind, nome, p in (("A", "recuo", {"t": 100, "x": 20, "k": 2}),
                                  ("B", "rompimento", {"n": 20, "m": 10, "k": 2})):
                _, pos, _ = b.simulate(df, kind, {**p, "vol": 0})
                dias = [{"t": str(i.date()), "o": r.Open, "h": r.High, "l": r.Low, "c": r.Close}
                        for i, r in df.iterrows()]
                for j in range(300, len(dias), 30):
                    s = sinais.LOGICAS[nome](dias[:j + 1], dias[j]["c"], **p)
                    self.assertEqual(s.quer == "comprado", pos.iloc[j] == 1, f"{ativo} {nome} dia {j}")


class FakeAlpaca:
    """Corretora de mentira: nada sai do computador."""
    ErroAlpaca = execucao.alpaca.ErroAlpaca

    def __init__(self, precos, posicoes=None, equity=100_000, last=100_000, cash=100_000):
        self.precos, self.pos = precos, posicoes or []
        self.c = {"equity": str(equity), "last_equity": str(last), "cash": str(cash), "status": "ACTIVE"}
        self.enviadas = []

    def conta(self): return self.c
    def posicoes(self): return self.pos

    def barras_diarias(self, simbolo, dias=0):
        p = self.precos[simbolo]
        return velas(p) + [{"t": "2026-hoje", "o": p[-1], "h": p[-1], "l": p[-1], "c": p[-1]}]

    def fechar_posicao(self, simbolo):
        q = next(float(p["qty"]) for p in self.pos if p["symbol"] == simbolo.replace("/", ""))
        self.enviadas.append((simbolo, "sell", q))
        return {"id": "x", "status": "accepted"}

    def enviar_ordem_mercado(self, simbolo, lado, q):
        self.enviadas.append((simbolo, lado, q))
        return {"id": "x", "status": "accepted"}


USAR_TESTE = {"BTC-USD": ("rompimento", {"n": 20, "m": 10, "k": 2.0}),
              "ETH-USD": ("rompimento", {"n": 20, "m": 10, "k": 2.0})}


class TestExecucao(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(execucao, "LOGS", self.tmp / "logs"),
                  mock.patch.object(execucao, "ESTADO", self.tmp / "estado.json"),
                  mock.patch.dict(sinais.USAR, USAR_TESTE)]
        for x in self.p: x.start()

    def tearDown(self):
        for x in self.p: x.stop()

    def eventos(self):
        f = next((self.tmp / "logs").glob("*.jsonl"))
        return [json.loads(l) for l in f.read_text().splitlines()]

    def estado(self):
        return json.loads((self.tmp / "estado.json").read_text())

    def rodar(self, fake, **kw):
        with mock.patch.object(execucao, "alpaca", fake):
            execucao.rodar(**kw)

    def test_compra_no_rompimento_respeita_1_porcento(self):
        fake = FakeAlpaca({"BTC/USD": ROMPEU_HOJE, "ETH/USD": CAINDO})
        self.rodar(fake)
        self.assertEqual(len(fake.enviadas), 1)
        simbolo, lado, q = fake.enviadas[0]
        self.assertEqual((simbolo, lado), ("BTC/USD", "buy"))
        est = self.estado()["BTC-USD"]
        self.assertEqual(est["logica"], "rompimento")
        self.assertLessEqual(q * (120 - est["stop"]), 1000)  # 1% de 100 mil

    def test_nao_recompra_o_mesmo_rompimento(self):
        fake = FakeAlpaca({"BTC/USD": ROMPEU_HOJE, "ETH/USD": CAINDO})
        self.rodar(fake)
        id_sinal = self.estado()["BTC-USD"]["id_sinal"]
        (self.tmp / "estado.json").write_text(json.dumps(
            {"BTC-USD": {"logica": "rompimento", "id_sinal": id_sinal}}))  # já vendeu (ex.: stop)
        fake2 = FakeAlpaca({"BTC/USD": ROMPEU_HOJE, "ETH/USD": CAINDO})
        self.rodar(fake2)
        self.assertEqual(fake2.enviadas, [])

    def test_sinal_antigo_nao_compra(self):
        fake = FakeAlpaca({"BTC/USD": ROMPEU_ANTES, "ETH/USD": ROMPEU_ANTES})
        self.rodar(fake)
        self.assertEqual(fake.enviadas, [])

    def test_troca_de_estrategia_vende_posicao_das_medias(self):
        (self.tmp / "estado.json").write_text(json.dumps({"ETH-USD": {"stop": 50, "compra": 300}}))
        fake = FakeAlpaca({"BTC/USD": CAINDO, "ETH/USD": CAINDO},
                          posicoes=[{"symbol": "ETHUSD", "qty": "2.5"}])
        self.rodar(fake)
        self.assertEqual(fake.enviadas, [("ETH/USD", "sell", 2.5)])
        venda = [e for e in self.eventos() if e["tipo"] == "ordem"][0]
        self.assertIn("troca de estratégia", venda["por_que"])

    def test_adota_posicao_antiga_se_rompimento_tambem_quer(self):
        (self.tmp / "estado.json").write_text(json.dumps({"BTC-USD": {"stop": 50, "compra": 100}}))
        fake = FakeAlpaca({"BTC/USD": ROMPEU_ANTES, "ETH/USD": CAINDO},
                          posicoes=[{"symbol": "BTCUSD", "qty": "1"}])
        self.rodar(fake)
        self.assertEqual(fake.enviadas, [])
        est = self.estado()["BTC-USD"]
        self.assertEqual(est["logica"], "rompimento")
        self.assertGreater(est["stop"], 50)

    def test_simular_nao_envia(self):
        fake = FakeAlpaca({"BTC/USD": ROMPEU_HOJE, "ETH/USD": ROMPEU_HOJE})
        self.rodar(fake, simular=True)
        self.assertEqual(fake.enviadas, [])
        self.assertEqual(sum(e["tipo"] == "simulada" for e in self.eventos()), 2)

    def test_limite_diario_veta_compra(self):
        fake = FakeAlpaca({"BTC/USD": ROMPEU_HOJE, "ETH/USD": CAINDO},
                          equity=96_000, last=100_000, cash=96_000)
        self.rodar(fake)
        self.assertEqual(fake.enviadas, [])
        self.assertTrue(any(e["tipo"] == "veto" for e in self.eventos()))

    def test_vende_no_stop(self):
        (self.tmp / "estado.json").write_text(json.dumps(
            {"BTC-USD": {"stop": 130, "logica": "rompimento"}}))
        fake = FakeAlpaca({"BTC/USD": ROMPEU_ANTES, "ETH/USD": CAINDO},
                          posicoes=[{"symbol": "BTCUSD", "qty": "1"}])
        self.rodar(fake)
        self.assertEqual(fake.enviadas, [("BTC/USD", "sell", 1.0)])

    def test_parar_bloqueia_tudo(self):
        with mock.patch("risco.parar_ligado", return_value=True):
            fake = FakeAlpaca({"BTC/USD": ROMPEU_HOJE, "ETH/USD": ROMPEU_HOJE})
            self.rodar(fake)
        self.assertEqual(fake.enviadas, [])

    def test_relatorio(self):
        fake = FakeAlpaca({"BTC/USD": ROMPEU_HOJE, "ETH/USD": CAINDO},
                          equity=96_000, last=100_000, cash=96_000)
        self.rodar(fake)
        dia = next((self.tmp / "logs").glob("*.jsonl")).stem
        with mock.patch.object(relatorio, "PASTA", self.tmp):
            txt = relatorio.gerar(dia)
        self.assertIn("Vetos do Robô de Risco (1)", txt)
        self.assertIn("$96.000,00", txt)
        self.assertIn("rompimento", txt)


class TestSoPaper(unittest.TestCase):
    def test_fechar_posicao_usa_paper(self):
        with mock.patch.object(execucao.alpaca, "_pedir", return_value={}) as p:
            execucao.alpaca.fechar_posicao("BTC/USD")
        p.assert_called_once_with("DELETE", "https://paper-api.alpaca.markets/v2/positions/BTCUSD")

    def test_bloqueia_conta_real(self):
        with self.assertRaises(execucao.alpaca.ErroAlpaca):
            execucao.alpaca._pedir("GET", "https://api.alpaca.markets/v2/account")


if __name__ == "__main__":
    unittest.main()
