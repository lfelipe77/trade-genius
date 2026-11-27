"""Fase 4: Robô de Execução (PAPER, dinheiro de mentira).

Roda sozinho no GitHub Actions (a cada 15 minutos). A cada rodada, para BTC e ETH:
  1. Pega as velas diárias na Alpaca.
  2. Pergunta a CADA estratégia (sinais.ESTRATEGIAS) o que fazer. Elas rodam
     em PARALELO na mesma conta, cada uma com a sua "carteira" em estado.json
     (quanto ela comprou, preço, stop, resultado), para comparar:
       - rompimento: fecha acima da máxima de N dias e da média de 200 = compra;
         fecha abaixo da mínima de M dias = vende.
       - media: comprado enquanto fecha acima da média de 50 dias, com stop
         móvel (sobe com o preço). Opera mais vezes.
     Sem promessa de lucro: um só ciclo de cripto no backtest.
  3. Se o preço cair até o stop da estratégia, ela vende a parte dela.
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
ESTADO = PASTA / "estado.json"   # carteira de cada estratégia: quantidade, compra, stop, placar
ATIVOS = {"BTC-USD": "BTC/USD", "ETH-USD": "ETH/USD"}  # nosso nome -> nome Alpaca
DIAS_HISTORICO = 400  # velas diárias pedidas (precisa de 200+ para a média)
MIN_DOLAR = 10.0  # ordens menores que isso não valem a pena
TAXA_ALPACA = 0.0025  # taxa aproximada da Alpaca em cripto, por lado (só para o placar)


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
    conta = Conta(patrimonio=float(c["equity"]),
                  patrimonio_inicio_dia=float(c.get("last_equity") or c["equity"]),
                  caixa=float(c["cash"]), posicoes=ler_posicoes())
    return conta, c


def ler_posicoes() -> dict:
    pos = {}
    for p in alpaca.posicoes():
        nome = p["symbol"].replace("/", "").replace("USD", "-USD")  # BTCUSD -> BTC-USD
        pos[nome] = float(p["qty"])
    return pos


def migrar(estado: dict, conta: Conta) -> dict:
    """estado.json antigo (uma estratégia só, chaves 'BTC-USD'...) -> carteiras por estratégia."""
    if not any(a in estado for a in ATIVOS):
        return estado
    novo = {k: v for k, v in estado.items() if k not in ATIVOS}
    cart = novo.setdefault("rompimento", {})
    for a in ATIVOS:
        if a in estado:
            info = dict(estado[a])
            tem = conta.posicoes.get(a, 0.0)
            if tem > 0 and info.get("stop") and "qtd" not in info:
                info["qtd"] = tem  # posição antiga era toda do rompimento
            cart[a] = info
    return novo


def qtd_de_outras(estado: dict, estrategia: str, ativo: str) -> float:
    return sum(estado.get(e, {}).get(ativo, {}).get("qtd", 0.0)
               for e in sinais.ESTRATEGIAS if e != estrategia)


def anotar_placar(estado: dict, estrategia: str, ganho: float) -> None:
    pl = estado.setdefault("placar", {}).setdefault(
        estrategia, {"resultado_usd": 0.0, "operacoes": 0, "acertos": 0})
    pl["resultado_usd"] = round(pl["resultado_usd"] + ganho, 2)
    pl["operacoes"] += 1
    pl["acertos"] += 1 if ganho > 0 else 0


def rodar(simular: bool = False) -> None:
    conta, bruto = montar_conta()
    antigo = ler_estado()
    estado = migrar(antigo, conta)
    if estado is not antigo:
        salvar_estado(estado)
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
        for estrategia in sinais.ESTRATEGIAS:
            rodar_estrategia(estrategia, nosso, simbolo, dias, preco, conta, estado, simular)


def rodar_estrategia(estrategia, nosso, simbolo, dias, preco, conta, estado, simular):
    logica, s = sinais.avaliar(nosso, dias, preco, estrategia)
    carteira = estado.setdefault(estrategia, {})
    info = carteira.get(nosso, {})
    # quanto ESTA estratégia tem (nunca mais do que a conta tem de verdade)
    tem = min(info.get("qtd", 0.0), conta.posicoes.get(nosso, 0.0))
    stop = info.get("stop")
    if tem > 0 and s.quer == "comprado" and s.stop_movel and stop and s.stop_movel > stop:
        stop = info["stop"] = s.stop_movel  # stop móvel: só sobe
        carteira[nosso] = info
        salvar_estado(estado)
    anotar({"tipo": "sinal", "estrategia": estrategia, "ativo": nosso, "preco": preco,
            "logica": logica, "sinal": s.quer, "motivo": s.motivo, "posicao": tem, "stop": stop})

    ordem = None
    if tem > 0 and stop and preco <= stop:
        motivo, ordem = "stop atingido", Ordem(nosso, "sell", tem, preco)
    elif tem > 0 and s.quer == "caixa":
        motivo, ordem = f"{logica}: {s.motivo}", Ordem(nosso, "sell", tem, preco)
    elif tem == 0 and s.quer == "comprado" and s.pode_comprar \
            and (s.id_sinal is None or info.get("id_sinal") != s.id_sinal):
        if not (s.stop and 0 < s.stop < preco):
            anotar({"tipo": "pulou", "estrategia": estrategia, "ativo": nosso, "motivo": "stop inválido"})
            return
        q = arredondar_baixo(tamanho_maximo(preco, s.stop, conta) * 0.98)  # folga p/ preço mexer
        if q * preco < MIN_DOLAR:
            anotar({"tipo": "pulou", "estrategia": estrategia, "ativo": nosso,
                    "motivo": "tamanho pequeno demais"})
            return
        motivo = f"{logica}: {s.motivo}"
        ordem = Ordem(nosso, "buy", q, preco, stop=s.stop)
    if ordem is None:
        return

    decisao = checar_ordem(ordem, conta)
    registro = {"estrategia": estrategia, "ativo": nosso, "lado": ordem.lado,
                "quantidade": ordem.quantidade, "preco": preco, "stop": ordem.stop,
                "por_que": motivo, "risco_disse": decisao.motivo}
    if not decisao.aprovada:
        anotar({"tipo": "veto", **registro})
        return
    if simular:
        anotar({"tipo": "simulada", **registro})
        return
    antes = conta.posicoes.get(nosso, 0.0)
    try:
        if ordem.lado == "sell" and qtd_de_outras(estado, estrategia, nosso) <= 0:
            r = alpaca.fechar_posicao(simbolo)  # ninguém mais tem: fecha a quantidade exata
        else:
            q = ordem.quantidade if ordem.lado == "buy" else arredondar_baixo(ordem.quantidade)
            r = alpaca.enviar_ordem_mercado(simbolo, ordem.lado, q)
    except alpaca.ErroAlpaca as e:
        anotar({"tipo": "erro", **registro, "motivo": str(e)})
        return
    anotar({"tipo": "ordem", **registro, "id_alpaca": r.get("id"), "status": r.get("status")})
    if ordem.lado == "buy":
        # a Alpaca desconta a taxa em moeda: guarda o que realmente entrou
        try:
            recebido = ler_posicoes().get(nosso, 0.0) - antes
        except alpaca.ErroAlpaca:
            recebido = 0.0
        if not (0 < recebido <= ordem.quantidade * 1.001):
            recebido = arredondar_baixo(ordem.quantidade * (1 - TAXA_ALPACA), 9)
        carteira[nosso] = {"qtd": recebido, "stop": ordem.stop, "compra": preco,
                           "logica": logica, "id_sinal": s.id_sinal}
        conta.caixa -= ordem.quantidade * preco
        conta.posicoes[nosso] = antes + recebido
    else:
        ganho = tem * (preco - info.get("compra", preco)) - tem * preco * TAXA_ALPACA
        anotar_placar(estado, estrategia, ganho)
        # guarda o id do sinal para não recomprar o mesmo sinal depois de vender
        carteira[nosso] = {"logica": logica, "id_sinal": info.get("id_sinal")}
        conta.posicoes[nosso] = max(0.0, antes - tem)
        conta.caixa += tem * preco
    salvar_estado(estado)


if __name__ == "__main__":
    try:
        rodar(simular="--simular" in sys.argv)
    except alpaca.ErroAlpaca as e:
        anotar({"tipo": "erro", "motivo": str(e)})
        sys.exit(1)
