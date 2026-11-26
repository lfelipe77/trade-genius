"""Fase 3: Robô de Risco.

Regras fixas em código. SEM inteligência artificial. Ele pode VETAR qualquer
ordem antes dela ir para a corretora. Nenhum outro robô passa por cima dele.

Regras (valores em risco_config.json):
  1. Botão de parar: se existir o arquivo PARAR na pasta do projeto, ou
     "parar_tudo" for true no config, TODAS as ordens são vetadas.
  2. Ordem precisa ser válida: ativo permitido, lado "buy"/"sell",
     quantidade e preço maiores que zero.
  3. Compra precisa de stop (preço de saída se der errado). Sem stop não dá
     para saber quanto pode perder, então é vetada.
  4. No máximo 1% da conta em risco por trade:
        risco = quantidade x (preço - stop) + custos de entrada e saída
  5. Limite de perda diária (padrão 3%): se a conta já caiu isso hoje, ou se
     esta compra puder passar do limite caso dê errado, a compra é vetada.
     Vendas que fecham posição continuam liberadas (elas diminuem o risco).
  6. Sem alavancagem: compra não pode custar mais que o dinheiro em caixa.
     Sem venda a descoberto: só vende o que tem.

Uso:
    from risco import Ordem, Conta, checar_ordem
    decisao = checar_ordem(ordem, conta)
    if decisao.aprovada: ...
    else: print(decisao.motivo)

Teste rápido: python risco.py
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

PASTA = Path(__file__).parent
CONFIG_PADRAO = PASTA / "risco_config.json"


@dataclass
class Ordem:
    ativo: str            # ex.: "BTC-USD"
    lado: str             # "buy" (compra) ou "sell" (venda)
    quantidade: float     # ex.: 0.01 BTC
    preco: float          # preço esperado de execução, em dólar
    stop: float | None = None  # preço de saída se der errado (obrigatório na compra)


@dataclass
class Conta:
    patrimonio: float           # valor total da conta agora (caixa + posições)
    patrimonio_inicio_dia: float  # valor total no começo do dia (UTC)
    caixa: float                # dinheiro livre para comprar
    posicoes: dict = field(default_factory=dict)  # ex.: {"BTC-USD": 0.02}


@dataclass
class Decisao:
    aprovada: bool
    motivo: str


def carregar_config(caminho: Path = CONFIG_PADRAO) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def parar_ligado(config: dict, pasta: Path = PASTA) -> bool:
    return bool(config.get("parar_tudo")) or (pasta / config.get("arquivo_parar", "PARAR")).exists()


def checar_ordem(ordem: Ordem, conta: Conta, config: dict | None = None,
                 pasta: Path = PASTA) -> Decisao:
    """Aprova ou veta uma ordem. Sempre devolve o motivo."""
    cfg = config if config is not None else carregar_config()

    # 1. Botão de parar
    if parar_ligado(cfg, pasta):
        return Decisao(False, "VETO: botão de parar ligado. Nenhuma ordem passa.")

    # 2. Ordem válida
    if ordem.ativo not in cfg["ativos_permitidos"]:
        return Decisao(False, f"VETO: ativo {ordem.ativo} não está na lista permitida.")
    if ordem.lado not in ("buy", "sell"):
        return Decisao(False, f"VETO: lado '{ordem.lado}' inválido (use buy ou sell).")
    if not (ordem.quantidade > 0 and ordem.preco > 0):
        return Decisao(False, "VETO: quantidade e preço precisam ser maiores que zero.")
    if not (conta.patrimonio > 0 and conta.patrimonio_inicio_dia > 0):
        return Decisao(False, "VETO: dados da conta inválidos (patrimônio zero ou negativo).")

    custo = cfg["custo_por_operacao"]

    # Venda: só fecha o que tem (sem venda a descoberto). Liberada mesmo
    # com limite diário batido, porque diminui o risco.
    if ordem.lado == "sell":
        tem = conta.posicoes.get(ordem.ativo, 0.0)
        if ordem.quantidade > tem + 1e-12:
            return Decisao(False, f"VETO: tentando vender {ordem.quantidade} mas só tem {tem} "
                                  f"de {ordem.ativo} (venda a descoberto não é permitida).")
        return Decisao(True, "APROVADA: venda que fecha posição (diminui o risco).")

    # Compra
    # 3. Stop obrigatório
    if ordem.stop is None:
        return Decisao(False, "VETO: compra sem stop. Sem stop não dá para medir o risco.")
    if not (0 < ordem.stop < ordem.preco):
        return Decisao(False, "VETO: stop da compra precisa estar abaixo do preço e acima de zero.")

    # 6. Sem alavancagem
    valor = ordem.quantidade * ordem.preco
    if valor * (1 + custo) > conta.caixa:
        return Decisao(False, f"VETO: compra de ${valor:,.2f} (+custos) é maior que o caixa "
                              f"${conta.caixa:,.2f}. Sem alavancagem.")

    # 4. Risco máximo por trade
    risco = ordem.quantidade * (ordem.preco - ordem.stop) \
        + valor * custo + ordem.quantidade * ordem.stop * custo
    limite_trade = conta.patrimonio * cfg["risco_max_por_trade"]
    if risco > limite_trade:
        return Decisao(False, f"VETO: risco de ${risco:,.2f} passa do máximo por trade "
                              f"${limite_trade:,.2f} ({cfg['risco_max_por_trade']:.0%} da conta).")

    # 5. Limite de perda diária
    perda_hoje = max(0.0, conta.patrimonio_inicio_dia - conta.patrimonio)
    limite_dia = conta.patrimonio_inicio_dia * cfg["perda_max_diaria"]
    if perda_hoje >= limite_dia:
        return Decisao(False, f"VETO: perda de hoje ${perda_hoje:,.2f} já bateu o limite diário "
                              f"${limite_dia:,.2f}. Só vendas até amanhã.")
    if perda_hoje + risco > limite_dia:
        return Decisao(False, f"VETO: se esta compra der errado, a perda do dia chega a "
                              f"${perda_hoje + risco:,.2f}, acima do limite ${limite_dia:,.2f}.")

    return Decisao(True, f"APROVADA: risco ${risco:,.2f} (máx ${limite_trade:,.2f}), "
                         f"perda de hoje ${perda_hoje:,.2f} (limite ${limite_dia:,.2f}).")


def tamanho_maximo(preco: float, stop: float, conta: Conta, config: dict | None = None) -> float:
    """Maior quantidade que passa na regra de 1% (ajuda os outros robôs)."""
    cfg = config if config is not None else carregar_config()
    custo = cfg["custo_por_operacao"]
    risco_por_unidade = (preco - stop) + preco * custo + stop * custo
    if risco_por_unidade <= 0:
        return 0.0
    por_risco = conta.patrimonio * cfg["risco_max_por_trade"] / risco_por_unidade
    por_caixa = conta.caixa / (preco * (1 + custo))
    return max(0.0, min(por_risco, por_caixa))


if __name__ == "__main__":
    conta = Conta(patrimonio=10_000, patrimonio_inicio_dia=10_000, caixa=10_000)
    exemplos = [
        Ordem("BTC-USD", "buy", 0.02, 90_000, stop=85_500),   # risco ~$95: ok
        Ordem("BTC-USD", "buy", 0.10, 90_000, stop=85_500),   # risco ~$476: veto
        Ordem("BTC-USD", "buy", 0.05, 90_000, stop=80_000),   # risco ~$513: veto
        Ordem("BTC-USD", "buy", 0.01, 90_000),                # sem stop: veto
        Ordem("ETH-USD", "sell", 1.0, 3_000),                 # não tem ETH: veto
    ]
    for o in exemplos:
        d = checar_ordem(o, conta)
        print(f"{o.lado} {o.quantidade} {o.ativo} @ {o.preco} stop={o.stop}\n  -> {d.motivo}")
    q = tamanho_maximo(90_000, 85_500, conta)
    print(f"\nMaior compra de BTC a $90.000 com stop $85.500: {q:.4f} BTC")
