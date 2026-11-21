"""Chamadas ao Claude (opcionais). Sem credenciais, o agente roda 100% offline.

Duas chamadas, ambas com papel limitado:
  1. classificar: entende a pergunta e devolve JSON validado (Pydantic / saída estruturada);
  2. redigir: explica a decisão JÁ TOMADA pelas regras, citando só os trechos fornecidos.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .modelos import Classificacao, Confianca, Decisao, Trecho

MODELO = "claude-opus-5-5"
# Se o modelo recusar por política de segurança, a API refaz a chamada em um modelo de fallback.
_FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

SISTEMA_CLASSIFICACAO = """Você classifica solicitações de colaboradores internos de um app de delivery \
sobre cancelamentos e reembolsos. Extraia apenas o que está explícito no texto.
- causa: quem causou o problema (restaurante, app, entregador, cliente). Se o texto não disser, use "indefinida".
  Desistência ou arrependimento do cliente = "cliente".
- status_relatado: use "desconhecido" se o texto não mencionar o status do pedido.
- pedido_id: só se um número de pedido aparecer no texto.
Nunca deduza a causa a partir do que seria "mais provável"."""

SISTEMA_REDACAO = """Você redige a resposta de um agente interno para um colaborador de atendimento \
(não para o cliente final), em português do Brasil.
Regras obrigatórias:
1. A decisão já foi tomada pelo motor de regras. Não a altere, não a suavize e não a contradiga.
2. Use somente as informações dos trechos da base e dos dados do pedido fornecidos. Não invente prazos, \
valores, percentuais ou políticas.
3. Cite cada afirmação de política com o ID do trecho no formato [#ID] e o nome da fonte.
4. Se a confiança não for alta, deixe claro que não há segurança para concluir e liste as ações de fallback.
5. Seja objetivo: no máximo 170 palavras, com as seções "Recomendação", "Por quê" e "Próximos passos"."""


def disponivel() -> bool:
    if os.getenv("AGENTE_MODO", "").lower() == "offline":
        return False
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
                or os.getenv("AGENTE_MODO", "").lower() == "claude")


class ClienteClaude:
    def __init__(self):
        import anthropic

        self._client = anthropic.Anthropic()

    def classificar(self, pergunta: str) -> Optional[Classificacao]:
        resp = self._client.beta.messages.parse(
            model=MODELO,
            max_tokens=4000,
            system=SISTEMA_CLASSIFICACAO,
            messages=[{"role": "user", "content": pergunta}],
            output_format=Classificacao,
            **_FALLBACK,
        )
        if resp.stop_reason == "refusal":
            return None
        return resp.parsed_output

    def redigir(self, pergunta: str, decisao: Decisao, trechos: list[Trecho], pedido: Optional[dict],
                confianca: Confianca, acoes: list[str]) -> Optional[str]:
        contexto = {
            "pergunta_do_colaborador": pergunta,
            "decisao_do_motor_de_regras": decisao.model_dump(mode="json"),
            "confianca": confianca.model_dump(),
            "acoes_de_fallback": acoes,
            "dados_do_pedido_api": pedido,
            "trechos_da_base": [t.model_dump(exclude={"score"}) for t in trechos],
        }
        resp = self._client.beta.messages.create(
            model=MODELO,
            max_tokens=8000,
            system=SISTEMA_REDACAO,
            messages=[{"role": "user", "content": json.dumps(contexto, ensure_ascii=False, indent=2)}],
            **_FALLBACK,
        )
        if resp.stop_reason == "refusal":
            return None
        texto = "".join(b.text for b in resp.content if b.type == "text").strip()
        return texto or None
