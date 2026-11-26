"""Robô de Preços (Fase 1 do Trade Genius).

Baixa 5 anos de preços diários (grátis, via yfinance) e salva em CSV na pasta data/.
Não faz nenhuma operação de compra ou venda.

Uso:
    python precos.py
"""
from pathlib import Path

import yfinance as yf

ATIVOS = ["BTC-USD", "ETH-USD"]  # Bitcoin e Ethereum, em dólares
PERIODO = "5y"                   # 5 anos
PASTA = Path(__file__).parent / "data"


def baixar(ativo: str) -> Path:
    df = yf.download(ativo, period=PERIODO, interval="1d",
                     auto_adjust=False, progress=False, multi_level_index=False)
    if df.empty:
        raise RuntimeError(f"Nenhum dado veio para {ativo}.")
    df = df[["Open", "High", "Low", "Close", "Adj Close", "Volume"]].dropna(how="all")
    df.index.name = "Date"
    arquivo = PASTA / f"{ativo}.csv"
    df.to_csv(arquivo, float_format="%.6f")
    print(f"{ativo}: {len(df)} dias, de {df.index[0].date()} até {df.index[-1].date()}"
          f" -> {arquivo.name}")
    return arquivo


def main() -> None:
    PASTA.mkdir(exist_ok=True)
    for ativo in ATIVOS:
        baixar(ativo)


if __name__ == "__main__":
    main()
