"""Entendimento da solicitação no modo offline (sem LLM).

Extrai intenção, causa, status e sinais de risco por palavras-chave. No modo Claude,
a mesma estrutura (`Classificacao`) é preenchida pelo modelo com saída estruturada;
este classificador continua sendo o plano B se a chamada falhar.
"""
from __future__ import annotations

import re

from .base_conhecimento import normalizar
from .modelos import Classificacao


def _tem(texto: str, termos: list[str]) -> bool:
    return any(t in texto for t in termos)


def classificar_offline(pergunta: str) -> Classificacao:
    t = normalizar(pergunta)

    m = re.search(r"\b(\d{4,})\b", t)
    pedido_id = m.group(1) if m else None

    if _tem(t, ["saiu para entrega", "saiu pra entrega", "despach", "a caminho", "em rota", "saida para entrega"]):
        status = "saiu_para_entrega"
    elif _tem(t, ["consta como entregue", "aparece como entregue", "marcado como entregue", "foi entregue"]):
        status = "entregue"
    elif _tem(t, ["antes do preparo", "aguardando preparo", "antes da preparacao", "ainda nao foi preparado"]):
        status = "aguardando_preparo"
    elif _tem(t, ["em preparo", "sendo preparado", "ja foi preparado"]):
        status = "em_preparo"
    elif _tem(t, ["cancelou", "cancelado", "cancelada"]):
        status = "cancelado"
    else:
        status = "desconhecido"

    causas = []
    if _tem(t, ["falta de ingrediente", "falta do item", "item indisponivel", "nao tinha o item", "nao tem o item"]) or (
        "restaurante" in t and _tem(t, ["cancelou", "erro", "errou", "falha", "nao tinha", "falta", "problema"])
    ):
        causas.append("restaurante")
    if _tem(t, ["erro do app", "erro no app", "falha do app", "falha no app", "app travou", "bug",
                "erro do aplicativo", "erro no aplicativo", "problema no app"]):
        causas.append("app")
    if _tem(t, ["entregador", "motoboy", "extravi", "entrega errada", "entregue errado", "entregou errado",
                "entrega incorreta"]):
        causas.append("entregador")
    if not causas and _tem(t, ["desist", "mudou de ideia", "nao quer mais", "arrepend", "cliente cancelou",
                               "cliente solicitou o cancelamento", "cliente pediu para cancelar"]):
        causas.append("cliente")
    causa = causas[0] if len(causas) == 1 else "indefinida"

    nao_autorizado = _tem(t, ["nao autorizou", "nao reconhece", "nao fez o pedido", "nao autorizado", "nao autorizada"])
    consta_entregue = _tem(t, ["consta como entregue", "aparece como entregue", "marcado como entregue"]) or (
        "nao chegou" in t and "entregue" in t
    )
    cobranca_duplicada = _tem(t, ["duas vezes", "duplicad", "cobrado de novo", "em dobro", "cobrado 2 vezes"])
    cobranca_apos = _tem(t, ["cobrad", "cobranca"]) and "cancel" in t
    fraude = _tem(t, ["fraude", "multiplos reembolsos", "varios reembolsos", "reembolsos seguidos", "golpe",
                      "muitos reembolsos"])

    if cobranca_duplicada or cobranca_apos:
        intencao = "financeiro"
    elif _tem(t, ["reembols", "estorno", "devolu", "dinheiro de volta"]):
        intencao = "reembolso"
    elif "cancel" in t:
        intencao = "cancelamento"
    elif _tem(t, ["pedido", "entrega", "restaurante", "politica", "cliente", "cobr", "pagamento", "ticket", "suporte"]):
        intencao = "duvida_politica"
    else:
        intencao = "fora_do_escopo"

    return Classificacao(
        intencao=intencao, causa=causa, status_relatado=status, pedido_id=pedido_id,
        nao_autorizado=nao_autorizado, consta_entregue_nao_chegou=consta_entregue,
        cobranca_apos_cancelamento=cobranca_apos, cobranca_duplicada=cobranca_duplicada,
        suspeita_fraude=fraude,
    )
