"""Teste das chaves da Alpaca (PAPER). Mostra só o status da conta, nunca as chaves.

Uso: python checar_chaves.py
"""
import sys

import alpaca

try:
    c = alpaca.conta()
except alpaca.ErroAlpaca as e:
    print(f"FALHOU: {e}")
    sys.exit(1)

print("OK: conectado na conta PAPER da Alpaca.")
print(f"Status: {c.get('status')}")
print(f"Patrimônio: ${float(c.get('equity', 0)):,.2f}")
print(f"Caixa: ${float(c.get('cash', 0)):,.2f}")
print(f"Cripto: {c.get('crypto_status')}")
