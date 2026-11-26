"""Robô de Preços por MINUTO (só leitura: não compra, não vende).

Baixa velas de 1 minuto (abertura, máxima, mínima, fechamento, volume) de:
  - Alpaca: BTC/USD e ETH/USD, últimos 7 dias (padrão)
  - Binance (dados PÚBLICOS, sem conta e sem chave): BTCUSDT e ETHUSDT, últimos 30 dias (padrão)

Salva em data/minuto/<fonte>_<par>_1m.csv.gz (CSV compactado; o pandas lê direto:
pd.read_csv("data/minuto/binance_BTCUSDT_1m.csv.gz")).

Uso:
  python dados_minuto.py                 # as duas fontes
  python dados_minuto.py --fonte alpaca  # só Alpaca
  python dados_minuto.py --fonte binance --dias-binance 30

As chaves da Alpaca (ALPACA_API_KEY / ALPACA_SECRET_KEY) são opcionais aqui:
dados de cripto da Alpaca funcionam sem chave. Se existirem, são usadas e
NUNCA são impressas.
"""

import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PASTA = os.path.join("data", "minuto")
COLUNAS = ["timestamp_utc", "open", "high", "low", "close", "volume", "trades"]

ALPACA_URL = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
ALPACA_PARES = ["BTC/USD", "ETH/USD"]

# data-api.binance.vision é o espelho só de dados de mercado (funciona fora da Binance "logada").
BINANCE_URLS = ["https://data-api.binance.vision/api/v3/klines",
                "https://api.binance.com/api/v3/klines"]
BINANCE_PARES = ["BTCUSDT", "ETHUSDT"]


def _get_json(url: str, cabecalhos: dict | None = None, tentativas: int = 4):
    req = urllib.request.Request(url, headers={"User-Agent": "trade-genius/1.0", **(cabecalhos or {})})
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tentativas - 1:
                time.sleep(2 ** i)
                continue
            raise
        except urllib.error.URLError:
            if i < tentativas - 1:
                time.sleep(2 ** i)
                continue
            raise


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def baixar_alpaca(par: str, dias: int) -> list[list]:
    fim = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    inicio = fim - timedelta(days=dias)
    cab = {}
    key, sec = os.environ.get("ALPACA_API_KEY", "").strip(), os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if key and sec:
        cab = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    linhas, token = [], None
    while True:
        q = {"symbols": par, "timeframe": "1Min", "start": _iso(inicio), "end": _iso(fim),
             "limit": 10000, "sort": "asc"}
        if token:
            q["page_token"] = token
        d = _get_json(ALPACA_URL + "?" + urllib.parse.urlencode(q), cab)
        for b in d.get("bars", {}).get(par, []):
            linhas.append([b["t"].replace("T", " ").rstrip("Z"), b["o"], b["h"], b["l"], b["c"], b["v"], b.get("n", "")])
        token = d.get("next_page_token")
        if not token:
            break
    return linhas


def _binance_base() -> str:
    for u in BINANCE_URLS:
        try:
            _get_json(u + "?symbol=BTCUSDT&interval=1m&limit=1", tentativas=1)
            return u
        except Exception as e:  # noqa: BLE001
            print(f"  aviso: {urllib.parse.urlparse(u).netloc} não respondeu ({e}); tentando o próximo")
    raise RuntimeError("Nenhum endereço da Binance respondeu.")


def baixar_binance(par: str, dias: int, base: str) -> list[list]:
    agora_ms = int(time.time() * 1000)
    inicio = agora_ms - dias * 86_400_000
    linhas = []
    while inicio < agora_ms:
        q = {"symbol": par, "interval": "1m", "startTime": inicio, "limit": 1000}
        k = _get_json(base + "?" + urllib.parse.urlencode(q))
        if not k:
            break
        for v in k:
            if v[6] >= agora_ms:  # vela ainda aberta: fica de fora
                continue
            t = datetime.fromtimestamp(v[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            linhas.append([t, v[1], v[2], v[3], v[4], v[5], v[8]])
        inicio = k[-1][0] + 60_000
        time.sleep(0.1)  # gentil com o limite público
    return linhas


def salvar(nome: str, linhas: list[list]) -> str:
    os.makedirs(PASTA, exist_ok=True)
    caminho = os.path.join(PASTA, f"{nome}_1m.csv.gz")
    # mtime=0: arquivo idêntico quando os dados são iguais (git não vê mudança à toa)
    with open(caminho, "wb") as bruto, gzip.GzipFile(fileobj=bruto, mode="wb", mtime=0) as gz:
        texto = [",".join(COLUNAS)] + [",".join(str(x) for x in l) for l in linhas]
        gz.write(("\n".join(texto) + "\n").encode())
    return caminho


def resumo(nome: str, linhas: list[list], caminho: str):
    if not linhas:
        print(f"  {nome}: NENHUMA vela recebida!")
        return
    print(f"  {nome}: {len(linhas):,} velas de 1 min | {linhas[0][0]} -> {linhas[-1][0]} UTC | "
          f"último fechamento {float(linhas[-1][4]):,.2f} | {caminho}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fonte", choices=["alpaca", "binance", "todas"], default="todas")
    p.add_argument("--dias-alpaca", type=int, default=7)
    p.add_argument("--dias-binance", type=int, default=30)
    a = p.parse_args()
    falhas = 0

    if a.fonte in ("alpaca", "todas"):
        print(f"Alpaca: últimos {a.dias_alpaca} dias")
        for par in ALPACA_PARES:
            try:
                l = baixar_alpaca(par, a.dias_alpaca)
                nome = "alpaca_" + par.replace("/", "")
                resumo(nome, l, salvar(nome, l))
                falhas += not l
            except Exception as e:  # noqa: BLE001
                print(f"  {par}: FALHOU ({e})")
                falhas += 1

    if a.fonte in ("binance", "todas"):
        print(f"Binance: últimos {a.dias_binance} dias")
        try:
            base = _binance_base()
            for par in BINANCE_PARES:
                l = baixar_binance(par, a.dias_binance, base)
                nome = "binance_" + par
                resumo(nome, l, salvar(nome, l))
                falhas += not l
        except Exception as e:  # noqa: BLE001
            print(f"  Binance FALHOU ({e})")
            falhas += 1

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
