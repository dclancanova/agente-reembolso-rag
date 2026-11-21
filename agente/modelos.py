"""Estruturas de dados compartilhadas pelo agente."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

Intencao = Literal["reembolso", "cancelamento", "financeiro", "duvida_politica", "fora_do_escopo"]
Causa = Literal["restaurante", "app", "entregador", "cliente", "indefinida"]
StatusPedido = Literal[
    "aguardando_preparo", "em_preparo", "saiu_para_entrega", "entregue", "cancelado", "desconhecido"
]


class Classificacao(BaseModel):
    """Saída da etapa de entendimento (LLM ou classificador offline)."""

    intencao: Intencao
    causa: Causa = Field(description="Quem causou o problema, segundo o relato do colaborador")
    status_relatado: StatusPedido = Field(description="Status do pedido citado no relato, se houver")
    pedido_id: Optional[str] = Field(default=None, description="Número do pedido, se informado")
    nao_autorizado: bool = Field(description="Cliente afirma que não autorizou o pedido/cobrança")
    consta_entregue_nao_chegou: bool = Field(description="Pedido consta como entregue, mas não chegou")
    cobranca_apos_cancelamento: bool = Field(description="Cliente foi cobrado após cancelamento")
    cobranca_duplicada: bool = Field(description="Suspeita de cobrança em duplicidade")
    suspeita_fraude: bool = Field(description="Relato menciona fraude ou reembolsos repetidos")


class Trecho(BaseModel):
    """Registro da base de conhecimento."""

    id: int
    categoria: str
    pergunta: str
    resposta: str
    fonte: str
    score: float = 0.0


class Resultado(str, Enum):
    REEMBOLSO_TOTAL = "reembolso_total"
    ESTORNO_AUTOMATICO = "estorno_automatico"
    VERIFICAR_ESTORNO = "verificar_estorno"
    PEDIR_INFORMACAO = "pedir_informacao"
    VALIDACAO_MANUAL = "validacao_manual"
    ANTIFRAUDE = "antifraude"
    ORIENTACAO = "orientacao"
    SEM_BASE = "sem_base"


class Decisao(BaseModel):
    """Saída do motor de regras: determinística e auditável."""

    resultado: Resultado
    regra: str = Field(description="Identificador da regra aplicada")
    explicacao: str = Field(description="Raciocínio da regra em linguagem simples")
    evidencias: list[int] = Field(description="IDs da base que sustentam a decisão")
    requer_humano: bool
    perguntas: list[str] = Field(default_factory=list, description="O que perguntar ao colaborador")


class Confianca(BaseModel):
    nivel: Literal["alta", "media", "baixa"]
    sinais: list[str]


class RespostaAgente(BaseModel):
    pergunta: str
    classificacao: Classificacao
    pedido: Optional[dict]
    trechos_recuperados: list[Trecho]
    decisao: Decisao
    confianca: Confianca
    acoes_fallback: list[str]
    resposta: str
    modo: str = Field(description="'claude' ou 'offline' e eventuais avisos")
