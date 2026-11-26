"""Fase 4: Robô de Execução (PAPER, dinheiro de mentira).

Roda sozinho no GitHub Actions (de hora em hora). A cada rodada, para BTC e ETH:
  1. Pega os fechamentos diários na Alpaca e calcula as médias de 50 e 200 dias.
  2. Sinal: média 50 acima da 200 = quer estar comprado. Abaixo = quer caixa.
     ATENÇÃO: esse sinal PERDEU para "comprar e segurar" no backtest (Fase 2).
     Aqui ele serve só para testar a mecânica (ordem -> risco -> corretora ->
     relatório), não para ganhar dinheiro.
  3. Stop de 5% abaixo do preço de compra. Se o preço cair até o stop, vende.
  4. TODA ordem passa pelo Robô de Risco (risco.py). Vetou = não envia.
  5. Anota tudo em logs/AAAA-MM-DD.jsonl (base do relatório diário).

Só fala com paper-api.alpaca.markets (ver alpaca.py). Nunca conta real.

Uso: python execucao.py            (precisa das variáveis ALPACA_API_KEY/SECRET)
     python execucao.py --simular  (calcula e passa no risco, mas NÃO envia ordem)
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import alpaca
from risco import Conta, Ordem, checar_ordem, tamanho_maximo

PASTA = Path(__file__).parent
LOGS = PASTA / "logs"
ESTADO = PASTA / "estado.json"   # guarda o stop de cada posição aberta
ATIVOS = {"BTC-USD": "BTC/USD", "ETH-USD": "ETH/USD"}  # nosso nome -> nome Alpaca
RAPIDA, LENTA = 50, 200
STOP_PCT = 0.05
MIN_DOLAR = 10.0  # ordens menores que isso não valem a pena


def agora() -> datetime:
    return datetime.now(timezone.utc)


def anotar(evento: dict) -> None:
    LOGS.mkdir(exist_ok=True)
    evento = {"hora": agora().strftime("%Y-%m-%dT%H:%M:%SZ"), **evento}
    with open(LOGS / f"{agora():%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    print(json.dumps(evento, ensure_ascii=False))


def ler_estado() -> dict:
    return json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}


def salvar_estado(estado: dict) -> None:
    ESTADO.write_text(json.dumps(estado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sinal(fechamentos: list[float]) -> str | None:
    """'comprado', 'caixa', ou None se não tem dados suficientes.

    Usa só dias COMPLETOS: o último candle (dia de hoje, em andamento) é ignorado.
    """
    completos = fechamentos[:-1]
    if len(completos) < LENTA:
        return None
    m_rapida = sum(completos[-RAPIDA:]) / RAPIDA
    m_lenta = sum(completos[-LENTA:]) / LENTA
    return "comprado" if m_rapida > m_lenta else "caixa"


def arredondar_baixo(q: float, casas: int = 6) -> float:
    f = 10 ** casas
    return math.floor(q * f) / f


def montar_conta() -> tuple[Conta, dict]:
    c = alpaca.conta()
    pos = {}
    for p in alpaca.posicoes():
        nome = p["symbol"].replace("/", "").replace("USD", "-USD")  # BTCUSD -> BTC-USD
        pos[nome] = float(p["qty"])
    conta = Conta(patrimonio=float(c["equity"]),
                  patrimonio_inicio_dia=float(c.get("last_equity") or c["equity"]),
                  caixa=float(c["cash"]), posicoes=pos)
    return conta, c


def rodar(simular: bool = False) -> None:
    conta, bruto = montar_conta()
    estado = ler_estado()
    anotar({"tipo": "conta", "patrimonio": conta.patrimonio,
            "patrimonio_inicio_dia": conta.patrimonio_inicio_dia,
            "caixa": conta.caixa, "posicoes": conta.posicoes, "status": bruto.get("status")})

    for nosso, simbolo in ATIVOS.items():
        barras = alpaca.barras_diarias(simbolo, dias=LENTA + 20)
        fech = [float(b["c"]) for b in barras]
        if not fech:
            anotar({"tipo": "erro", "ativo": nosso, "motivo": "sem preços da Alpaca"})
            continue
        preco = fech[-1]
        s = sinal(fech)
        tem = conta.posicoes.get(nosso, 0.0)
        stop = estado.get(nosso, {}).get("stop")
        anotar({"tipo": "sinal", "ativo": nosso, "preco": preco, "sinal": s,
                "posicao": tem, "stop": stop})

        ordem = None
        if tem > 0 and ((stop and preco <= stop) or s == "caixa"):
            motivo = "stop atingido" if (stop and preco <= stop) else "sinal virou caixa"
            ordem = Ordem(nosso, "sell", tem, preco)
        elif tem == 0 and s == "comprado":
            novo_stop = round(preco * (1 - STOP_PCT), 2)
            q = arredondar_baixo(tamanho_maximo(preco, novo_stop, conta) * 0.98)  # folga p/ preço mexer
            if q * preco < MIN_DOLAR:
                anotar({"tipo": "pulou", "ativo": nosso, "motivo": "tamanho pequeno demais"})
                continue
            motivo = "sinal comprado (média 50 > 200)"
            ordem = Ordem(nosso, "buy", q, preco, stop=novo_stop)
        if ordem is None:
            continue

        decisao = checar_ordem(ordem, conta)
        registro = {"ativo": nosso, "lado": ordem.lado, "quantidade": ordem.quantidade,
                    "preco": preco, "stop": ordem.stop, "por_que": motivo,
                    "risco_disse": decisao.motivo}
        if not decisao.aprovada:
            anotar({"tipo": "veto", **registro})
            continue
        if simular:
            anotar({"tipo": "simulada", **registro})
            continue
        try:
            r = alpaca.enviar_ordem_mercado(simbolo, ordem.lado, ordem.quantidade)
        except alpaca.ErroAlpaca as e:
            anotar({"tipo": "erro", **registro, "motivo": str(e)})
            continue
        anotar({"tipo": "ordem", **registro, "id_alpaca": r.get("id"), "status": r.get("status")})
        if ordem.lado == "buy":
            estado[nosso] = {"stop": ordem.stop, "compra": preco}
            conta.caixa -= ordem.quantidade * preco
        else:
            estado.pop(nosso, None)
        salvar_estado(estado)


if __name__ == "__main__":
    try:
        rodar(simular="--simular" in sys.argv)
    except alpaca.ErroAlpaca as e:
        anotar({"tipo": "erro", "motivo": str(e)})
        sys.exit(1)
