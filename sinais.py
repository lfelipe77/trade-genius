"""Sinais (lógicas de compra e venda) do Robô de Execução.

Cada lógica é uma função que recebe os dias COMPLETOS (velas diárias, a mais
velha primeiro, cada uma {"o","h","l","c"}) e o preço de agora, e devolve um
Sinal. O Robô de Risco continua tendo a palavra final em toda ordem.

Para ADICIONAR uma lógica nova:
  1. escreva uma função  minha_logica(dias, preco, **params) -> Sinal
  2. registre em LOGICAS = {"nome": minha_logica}
  3. escolha qual ativo usa qual lógica em USAR

Sinal:
  quer   "comprado" ou "caixa" (o que a lógica quer ter agora)
  pode_comprar  True se é um bom momento para ENTRAR agora
  stop   preço de saída se der errado (para uma compra nova)
  id_sinal  identifica o sinal de entrada (para não comprar 2x o mesmo sinal)
  motivo  explicação curta, em português (vai para o relatório)
"""

from dataclasses import dataclass


@dataclass
class Sinal:
    quer: str
    pode_comprar: bool
    stop: float | None
    id_sinal: str | None
    motivo: str


# ------------------------------------------------------------ ajudantes
def media(xs):
    return sum(xs) / len(xs)


def atr(dias, n=14):
    """Média do 'tamanho real' das últimas n velas (mede a agitação do preço)."""
    trs = []
    for i in range(len(dias) - n, len(dias)):
        d, ant = dias[i], dias[i - 1]["c"]
        trs.append(max(d["h"] - d["l"], abs(d["h"] - ant), abs(d["l"] - ant)))
    return media(trs)


# ------------------------------------------------------------ lógica 1
def medias(dias, preco, rapida=50, lenta=200, stop_pct=0.05):
    """Médias 50/200 (PERDEU para comprar e segurar no backtest)."""
    if len(dias) < lenta:
        return Sinal("caixa", False, None, None, "poucos dados")
    fech = [d["c"] for d in dias]
    if media(fech[-rapida:]) > media(fech[-lenta:]):
        return Sinal("comprado", True, round(preco * (1 - stop_pct), 2), None,
                     f"média {rapida} acima da {lenta}")
    return Sinal("caixa", False, None, None, f"média {rapida} abaixo da {lenta}")


# ------------------------------------------------------------ lógica 2
def rompimento(dias, preco, n=20, m=10, k=2.0):
    """Rompimento (backtest_seletivo.py, estratégia B).

    ENTRA quando o dia fecha acima da máxima dos n dias anteriores E acima
    da média de 200 dias. SAI quando um dia fecha abaixo da mínima dos m dias
    anteriores, ou no stop (entrada - k x ATR de 14 dias).

    Para saber se a lógica "estaria comprada" hoje, ela repassa o histórico
    inteiro dia a dia (igual ao backtest), sem olhar o futuro.
    """
    inicio = max(200, n, m, 15)
    if len(dias) <= inicio:
        return Sinal("caixa", False, None, None, "poucos dados")
    dentro, stop, entrada_i = False, 0.0, None
    for i in range(inicio, len(dias)):
        d = dias[i]
        if dentro:
            if d["l"] <= stop:
                dentro = False
                continue  # não recompra no mesmo dia do stop
            if d["c"] < min(x["l"] for x in dias[i - m:i]):
                dentro = False
            continue
        maxima = max(x["h"] for x in dias[i - n:i])
        sma200 = media([x["c"] for x in dias[i - 199:i + 1]])
        if d["c"] > maxima and d["c"] > sma200:
            dentro, entrada_i = True, i
            stop = d["c"] - k * atr(dias[:i + 1])
    ultimo = len(dias) - 1
    if not dentro:
        return Sinal("caixa", False, None, None,
                     f"sem rompimento (precisa fechar acima da máxima de {n} dias e da média de 200)")
    fresco = entrada_i == ultimo  # rompeu no último dia completo
    novo_stop = round(preco - k * atr(dias), 2)
    return Sinal("comprado", fresco, novo_stop, dias[entrada_i].get("t", str(entrada_i)),
                 f"rompeu a máxima de {n} dias" + ("" if fresco else " (sinal antigo, não entra atrasado)"))


# ------------------------------------------------------------ lógica 3 (DESLIGADA)
def rsi3_serie(fech, alfa=1 / 3):
    """RSI de 3 dias (0 a 100). Abaixo de 20 = caiu forte e rápido."""
    out, up, dn = [None], None, None
    for a, b in zip(fech, fech[1:]):
        d = b - a
        u, w = max(d, 0.0), max(-d, 0.0)
        up = u if up is None else up + alfa * (u - up)
        dn = w if dn is None else dn + alfa * (w - dn)
        out.append(100.0 if dn == 0 else 100 - 100 / (1 + up / dn))
    return out


def recuo(dias, preco, t=100, x=20, k=2.0, saida=65, max_dias=15):
    """Comprar a queda (backtest_seletivo.py, estratégia A). DESLIGADA.

    ENTRA quando o preço está acima da média de t dias (tendência de alta) e
    o RSI(3) cai abaixo de x (queda forte). SAI quando o RSI(3) passa de
    'saida', depois de max_dias, ou no stop (entrada - k x ATR).
    No backtest ela PERDEU dinheiro sem filtro extra. Só ligar se um novo
    teste (com custos) passar E o Felipe aprovar.
    """
    inicio = max(t, 15)
    if len(dias) <= inicio:
        return Sinal("caixa", False, None, None, "poucos dados")
    fech = [d["c"] for d in dias]
    rsi = rsi3_serie(fech)
    dentro, stop, entrada_i, segurou = False, 0.0, None, 0
    for i in range(inicio, len(dias)):
        d = dias[i]
        if dentro:
            segurou += 1
            if d["l"] <= stop:
                dentro = False
                continue
            if rsi[i] > saida or segurou >= max_dias:
                dentro = False
            continue
        if d["c"] > media(fech[i - t + 1:i + 1]) and rsi[i] < x:
            dentro, entrada_i, segurou = True, i, 0
            stop = d["c"] - k * atr(dias[:i + 1])
    if not dentro:
        return Sinal("caixa", False, None, None, f"sem queda forte em tendência de alta (RSI3 {rsi[-1]:.0f})")
    fresco = entrada_i == len(dias) - 1
    return Sinal("comprado", fresco, round(preco - k * atr(dias), 2), dias[entrada_i].get("t", str(entrada_i)),
                 f"queda forte (RSI3 abaixo de {x}) em tendência de alta"
                 + ("" if fresco else " (sinal antigo, não entra atrasado)"))


# ------------------------------------------------------------ escolha
LOGICAS = {"medias": medias, "rompimento": rompimento, "recuo": recuo}

# Qual lógica cada ativo usa, com os parâmetros escolhidos no backtest
# walk-forward (backtest_seletivo.py). Trocar aqui = trocar a estratégia.
# "recuo" existe mas está DESLIGADA: para ligar, troque o nome aqui (por
# exemplo ("recuo", {"t": 100, "x": 20, "k": 2.0})) só depois de um backtest
# com custos que passe e da aprovação do Felipe.
USAR = {
    "BTC-USD": ("rompimento", {"n": 20, "m": 10, "k": 2.0}),
    "ETH-USD": ("rompimento", {"n": 40, "m": 20, "k": 2.0}),
}


def avaliar(ativo, dias, preco):
    nome, params = USAR[ativo]
    return nome, LOGICAS[nome](dias, preco, **params)
