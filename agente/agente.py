"""Orquestração do agente híbrido.

  pergunta
    → 1. entender (Claude com saída estruturada | classificador offline)
    → 2. consultar fontes da verdade: API de pedidos (fatos) + base de conhecimento (RAG)
    → 3. decidir (motor de regras determinístico)
    → 4. avaliar confiança (sinais objetivos) e definir fallback
    → 5. redigir (Claude, com validação de grounding | modelo determinístico)
    → 6. registrar log de auditoria
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import confianca as conf
from . import llm
from .api_pedidos import ApiPedidos
from .base_conhecimento import BaseConhecimento
from .classificador import classificar_offline
from .modelos import RespostaAgente
from .redator import redigir_modelo, validar_resposta_llm
from .regras import decidir

_LOG = Path(__file__).resolve().parent.parent / "logs" / "decisoes.jsonl"


class AgenteReembolso:
    def __init__(self, usar_claude: Optional[bool] = None, usar_embeddings: bool = True,
                 log: Optional[Path] = _LOG):
        self.base = BaseConhecimento(usar_embeddings=usar_embeddings)
        self.api = ApiPedidos()
        self.log = log
        usar_claude = llm.disponivel() if usar_claude is None else usar_claude
        self.claude = None
        if usar_claude:
            try:
                self.claude = llm.ClienteClaude()
            except Exception:  # sem credenciais ou SDK indisponível: segue offline
                self.claude = None

    @property
    def modo(self) -> str:
        return "claude" if self.claude else "offline"

    def responder(self, pergunta: str) -> RespostaAgente:
        avisos: list[str] = []

        # 1. Entender
        classificacao = None
        if self.claude:
            try:
                classificacao = self.claude.classificar(pergunta)
            except Exception as e:  # degradação graciosa: sem LLM, o agente segue com o plano B
                avisos.append(f"classificação via Claude falhou ({type(e).__name__}); usando offline")
        if classificacao is None:
            classificacao = classificar_offline(pergunta)

        # 2. Fontes da verdade
        pedido = self.api.consultar(classificacao.pedido_id)
        trechos = self.base.buscar(pergunta, k=4)

        # 3. Decidir
        decisao = decidir(classificacao, pedido, trechos, self.base.limiar)

        # 4. Confiança e fallback
        confianca = conf.avaliar(classificacao, pedido, trechos, decisao, self.base.limiar)
        acoes = conf.acoes_fallback(confianca, decisao)

        # 5. Redigir
        evidencias = self.base.por_ids(decisao.evidencias)
        contexto = {t.id: t for t in [*evidencias, *trechos]}
        resposta = None
        if self.claude:
            try:
                resposta = self.claude.redigir(pergunta, decisao, list(contexto.values()), pedido, confianca, acoes)
                problemas = validar_resposta_llm(resposta or "", set(contexto),
                                                 {t.fonte for t in contexto.values()}, pedido)
                if problemas:
                    avisos.append("resposta do Claude reprovada na validação: " + "; ".join(problemas))
                    resposta = None
            except Exception as e:
                avisos.append(f"redação via Claude falhou ({type(e).__name__})")
                resposta = None
        if resposta is None:
            resposta = redigir_modelo(decisao, evidencias, confianca, acoes, pedido)

        modo = self.modo if not avisos else f"{self.modo} (avisos: {' | '.join(avisos)})"
        resultado = RespostaAgente(
            pergunta=pergunta, classificacao=classificacao, pedido=pedido, trechos_recuperados=trechos,
            decisao=decisao, confianca=confianca, acoes_fallback=acoes, resposta=resposta, modo=modo,
        )
        self._registrar(resultado)
        return resultado

    def _registrar(self, r: RespostaAgente) -> None:
        if not self.log:
            return
        self.log.parent.mkdir(parents=True, exist_ok=True)
        registro = {
            "quando": datetime.now(timezone.utc).isoformat(),
            "pergunta": r.pergunta,
            "classificacao": r.classificacao.model_dump(),
            "pedido": r.pedido["id"] if r.pedido else None,
            "trechos": [(t.id, t.score) for t in r.trechos_recuperados],
            "regra": r.decisao.regra,
            "resultado": r.decisao.resultado.value,
            "evidencias": r.decisao.evidencias,
            "confianca": r.confianca.nivel,
            "modo": r.modo,
        }
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
