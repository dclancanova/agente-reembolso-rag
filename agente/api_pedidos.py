"""API de pedidos fictícia (fonte da verdade para dados factuais).

Na arquitetura, status, valor e pagamento NUNCA vêm da base de conhecimento:
vêm sempre de uma API (base: registro #15, "Integração API").
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

LIMITE_REEMBOLSOS_30D = 3  # a base não define o limite (lacuna); valor configurável da POC

_ARQUIVO = Path(__file__).resolve().parent.parent / "data" / "pedidos_mock.json"


class ApiPedidos:
    def __init__(self, arquivo: Path = _ARQUIVO):
        self._pedidos = json.loads(arquivo.read_text(encoding="utf-8"))["pedidos"]

    def consultar(self, pedido_id: Optional[str]) -> Optional[dict]:
        if not pedido_id:
            return None
        pedido = self._pedidos.get(str(pedido_id))
        return {"id": str(pedido_id), **pedido} if pedido else None
