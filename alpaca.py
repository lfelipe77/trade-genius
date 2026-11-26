"""Conexão com a Alpaca, SÓ a conta de PAPEL (dinheiro de mentira).

As chaves vêm de variáveis de ambiente (ALPACA_API_KEY e ALPACA_SECRET_KEY),
que no GitHub Actions vêm dos "secrets" do repositório. Elas NUNCA são
impressas nem salvas em arquivo.

O endereço da conta real (api.alpaca.markets) é bloqueado de propósito:
este código só fala com paper-api.alpaca.markets.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

PAPER = "https://paper-api.alpaca.markets/v2"
DADOS = "https://data.alpaca.markets/v1beta3/crypto/us"


class ErroAlpaca(RuntimeError):
    pass


def _chaves() -> dict:
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    sec = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key:
        raise ErroAlpaca("Secret ALPACA_API_KEY está vazia ou não existe.")
    if not sec:
        raise ErroAlpaca("Secret ALPACA_SECRET_KEY está vazia ou não existe.")
    if key == sec:
        raise ErroAlpaca("ALPACA_API_KEY e ALPACA_SECRET_KEY são IGUAIS. "
                         "A ALPACA_SECRET_KEY precisa ser a 'Secret Key' (a mais longa).")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}


def _pedir(metodo: str, url: str, corpo: dict | None = None):
    if not (url.startswith(PAPER) or url.startswith(DADOS)):
        raise ErroAlpaca("Bloqueado: só a conta de PAPEL da Alpaca é permitida.")
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo, headers={
        **_chaves(), "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            texto = r.read().decode()
            return json.loads(texto) if texto else None
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:300]
        if e.code in (401, 403):
            raise ErroAlpaca(f"Alpaca recusou as chaves (HTTP {e.code}). Confira se as duas "
                             f"secrets são da conta PAPER e estão certas.") from None
        raise ErroAlpaca(f"Alpaca respondeu HTTP {e.code}: {msg}") from None


def conta() -> dict:
    return _pedir("GET", f"{PAPER}/account")


def posicoes() -> list:
    return _pedir("GET", f"{PAPER}/positions")


def ordens_de_hoje(desde_iso: str) -> list:
    q = urllib.parse.urlencode({"status": "all", "after": desde_iso, "limit": 100})
    return _pedir("GET", f"{PAPER}/orders?{q}")


def enviar_ordem_mercado(simbolo: str, lado: str, quantidade: float) -> dict:
    """simbolo no formato da Alpaca, ex.: 'BTC/USD'."""
    return _pedir("POST", f"{PAPER}/orders", {
        "symbol": simbolo, "qty": f"{quantidade:.6f}", "side": lado,
        "type": "market", "time_in_force": "gtc"})


def barras_diarias(simbolo: str, dias: int = 260) -> list:
    """Fechamentos diários (UTC) do mais antigo para o mais novo."""
    from datetime import datetime, timedelta, timezone
    inicio = (datetime.now(timezone.utc) - timedelta(days=dias + 5)).strftime("%Y-%m-%dT00:00:00Z")
    barras, token = [], None
    while True:
        q = {"symbols": simbolo, "timeframe": "1Day", "start": inicio, "limit": 1000}
        if token:
            q["page_token"] = token
        r = _pedir("GET", f"{DADOS}/bars?{urllib.parse.urlencode(q)}")
        barras += r.get("bars", {}).get(simbolo, [])
        token = r.get("next_page_token")
        if not token:
            return barras
