"""Fase 4: Relatório diário (em português, simples).

Lê logs/AAAA-MM-DD.jsonl e a conta PAPER da Alpaca, e escreve
relatorios/AAAA-MM-DD.md com: patrimônio, ordens enviadas, vetos do Robô de Risco.

Uso: python relatorio.py [AAAA-MM-DD]   (padrão: hoje, UTC)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PASTA = Path(__file__).parent
CAPITAL_INICIAL = 100_000.0  # conta paper da Alpaca começa com $100 mil


def dinheiro(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"${s}"


def gerar(dia: str, conta_atual: dict | None = None) -> str:
    arq = PASTA / "logs" / f"{dia}.jsonl"
    eventos = [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if arq.exists() else []
    contas = [e for e in eventos if e["tipo"] == "conta"]
    ordens = [e for e in eventos if e["tipo"] == "ordem"]
    vetos = [e for e in eventos if e["tipo"] == "veto"]
    erros = [e for e in eventos if e["tipo"] == "erro"]
    sinais = {}
    for e in eventos:
        if e["tipo"] == "sinal":
            sinais[e["ativo"]] = e

    if conta_atual:
        patrimonio = float(conta_atual["equity"])
        inicio = float(conta_atual.get("last_equity") or patrimonio)
        caixa = float(conta_atual["cash"])
    elif contas:
        patrimonio, inicio, caixa = (contas[-1]["patrimonio"], contas[-1]["patrimonio_inicio_dia"],
                                     contas[-1]["caixa"])
    else:
        patrimonio = inicio = caixa = None

    L = [f"# Relatório do dia {dia}", "",
         "> Dinheiro de **mentira** (paper). Estratégia médias 50/200 = só teste da mecânica:",
         "> ela perdeu para \"comprar e segurar\" no backtest. Nada aqui é promessa de lucro.", ""]
    if patrimonio is not None:
        dia_pct = (patrimonio / inicio - 1) * 100 if inicio else 0
        tot_pct = (patrimonio / CAPITAL_INICIAL - 1) * 100
        L += ["## 💰 Conta", "",
              f"- Patrimônio: **{dinheiro(patrimonio)}**",
              f"- Hoje: {dia_pct:+.2f}%  |  Desde o início: {tot_pct:+.2f}%",
              f"- Caixa livre: {dinheiro(caixa)}", ""]
    else:
        L += ["## 💰 Conta", "", "- Sem dados da conta hoje.", ""]

    L += ["## 📈 Sinais (última checagem)", ""]
    if sinais:
        for a, e in sinais.items():
            sig = {"comprado": "🟢 comprado", "caixa": "⚪ caixa"}.get(e["sinal"], "❔ sem dados")
            L.append(f"- {a}: preço {dinheiro(e['preco'])}, sinal {sig}, posição {e['posicao']}")
    else:
        L.append("- Nenhuma checagem hoje.")
    L.append("")

    L += [f"## ✅ Ordens enviadas ({len(ordens)})", ""]
    L += [f"- {e['hora'][11:16]} UTC: {'COMPRA' if e['lado'] == 'buy' else 'VENDA'} "
          f"{e['quantidade']} {e['ativo']} a ~{dinheiro(e['preco'])} ({e['por_que']})"
          for e in ordens] or ["- Nenhuma."]
    L.append("")
    L += [f"## 🛑 Vetos do Robô de Risco ({len(vetos)})", ""]
    L += [f"- {e['hora'][11:16]} UTC: {e['lado']} {e['ativo']}: {e['risco_disse']}" for e in vetos] \
        or ["- Nenhum."]
    L.append("")
    if erros:
        L += [f"## ⚠️ Erros ({len(erros)})", ""]
        L += [f"- {e['hora'][11:16]} UTC: {e.get('motivo')}" for e in erros]
        L.append("")
    L.append(f"_Rodadas hoje: {len(contas)}_")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    dia = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conta = None
    try:
        import alpaca
        conta = alpaca.conta()
    except Exception as e:  # relatório sai mesmo sem conexão
        print(f"Aviso: sem conta ao vivo ({e}). Usando o log.")
    texto = gerar(dia, conta)
    pasta = PASTA / "relatorios"
    pasta.mkdir(exist_ok=True)
    (pasta / f"{dia}.md").write_text(texto, encoding="utf-8")
    print(texto)
