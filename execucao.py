"""Fase 4: Robô de Execução (PAPER, dinheiro de mentira).

Roda sozinho no GitHub Actions (a cada 15 minutos). A cada rodada, para BTC e ETH:
  1. Pega as velas diárias na Alpaca.
  2. Pergunta à lógica do ativo (sinais.py) o que fazer. Hoje: ROMPIMENTO
     (fecha acima da máxima de N dias e da média de 200 = compra; fecha abaixo
     da mínima de M dias = vende). Ele ganhou no backtest walk-forward, mas o
     lucro veio de poucas operações. Pode ser sorte. Sem promessa de lucro.
  3. Se o preço cair até o stop, vende.
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
import sinais
from risco import Conta, Ordem, checar_ordem, tamanho_maximo

PASTA = Path(__file__).parent
LOGS = PASTA / "logs"
ESTADO = PASTA / "estado.json"   # guarda o stop de cada posição aberta
ATIVOS = {"BTC-USD": "BTC/USD", "ETH-USD": "ETH/USD"}  # nosso nome -> nome Alpaca
DIAS_HISTORICO = 400  # velas diárias pedidas (precisa de 200+ para a média)
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
        barras = alpaca.barras_diarias(simbolo, dias=DIAS_HISTORICO)
        if not barras:
            anotar({"tipo": "erro", "ativo": nosso, "motivo": "sem preços da Alpaca"})
            continue
        preco = float(barras[-1]["c"])
        dias = [{"t": b["t"][:10], "o": float(b["o"]), "h": float(b["h"]),
                 "l": float(b["l"]), "c": float(b["c"])} for b in barras[:-1]]  # só dias completos
        logica, s = sinais.avaliar(nosso, dias, preco)
        tem = conta.posicoes.get(nosso, 0.0)
        info = estado.get(nosso, {})
        stop = info.get("stop")
        anotar({"tipo": "sinal", "ativo": nosso, "preco": preco, "logica": logica,
                "sinal": s.quer, "motivo": s.motivo, "posicao": tem, "stop": stop})

        ordem = None
        if tem > 0 and stop and preco <= stop:
            motivo, ordem = "stop atingido", Ordem(nosso, "sell", tem, preco)
        elif tem > 0 and s.quer == "caixa":
            motivo = f"{logica}: {s.motivo}"
            if info.get("logica", "medias") != logica:
                motivo = f"troca de estratégia para {logica}, que hoje quer caixa ({s.motivo})"
            ordem = Ordem(nosso, "sell", tem, preco)
        elif tem > 0 and info.get("logica", "medias") != logica:
            # posição antiga que a nova lógica também quer: adota, com o stop da nova lógica
            estado[nosso] = {**info, "logica": logica, "stop": s.stop, "id_sinal": s.id_sinal}
            salvar_estado(estado)
            anotar({"tipo": "adotou", "ativo": nosso, "logica": logica, "stop": s.stop})
        elif tem == 0 and s.quer == "comprado" and s.pode_comprar \
                and (s.id_sinal is None or info.get("id_sinal") != s.id_sinal):
            if not (s.stop and 0 < s.stop < preco):
                anotar({"tipo": "pulou", "ativo": nosso, "motivo": "stop inválido"})
                continue
            q = arredondar_baixo(tamanho_maximo(preco, s.stop, conta) * 0.98)  # folga p/ preço mexer
            if q * preco < MIN_DOLAR:
                anotar({"tipo": "pulou", "ativo": nosso, "motivo": "tamanho pequeno demais"})
                continue
            motivo = f"{logica}: {s.motivo}"
            ordem = Ordem(nosso, "buy", q, preco, stop=s.stop)
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
            estado[nosso] = {"stop": ordem.stop, "compra": preco, "logica": logica,
                             "id_sinal": s.id_sinal}
            conta.caixa -= ordem.quantidade * preco
        else:
            # guarda o id do sinal para não recomprar o mesmo rompimento depois de vender
            estado[nosso] = {"logica": logica, "id_sinal": info.get("id_sinal")}
        salvar_estado(estado)


if __name__ == "__main__":
    try:
        rodar(simular="--simular" in sys.argv)
    except alpaca.ErroAlpaca as e:
        anotar({"tipo": "erro", "motivo": str(e)})
        sys.exit(1)
