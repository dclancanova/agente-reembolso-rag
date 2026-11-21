"""Nível de confiança a partir de sinais objetivos (não da autoavaliação do LLM)
e ações de fallback definidas pela própria base (Fluxo Suporte, registros #11 e #12).
"""
from __future__ import annotations

from typing import Optional

from .modelos import Classificacao, Confianca, Decisao, Resultado, Trecho

LINK_SUPORTE = "https://suporte-interno.exemplo/reembolsos/novo-ticket"  # link fictício da POC

_DECISOES_FINANCEIRAS = {Resultado.REEMBOLSO_TOTAL, Resultado.ESTORNO_AUTOMATICO}


def avaliar(c: Classificacao, pedido: Optional[dict], trechos: list[Trecho], decisao: Decisao,
            limiar: float) -> Confianca:
    sinais: list[str] = []
    nivel = "alta"

    def rebaixar(para: str, motivo: str) -> None:
        nonlocal nivel
        ordem = {"alta": 2, "media": 1, "baixa": 0}
        if ordem[para] < ordem[nivel]:
            nivel = para
        sinais.append(motivo)

    melhor = max((t.score for t in trechos), default=0.0)
    if melhor < limiar:
        rebaixar("baixa", f"Busca fraca na base (melhor score {melhor:.2f} < limiar {limiar:.2f})")
    else:
        sinais.append(f"Base cobre a pergunta (melhor score {melhor:.2f})")

    if decisao.requer_humano:
        rebaixar("baixa", f"Regra {decisao.regra} exige análise humana")
    if decisao.resultado == Resultado.SEM_BASE:
        rebaixar("baixa", "Nenhuma política aplicável encontrada")
    if decisao.perguntas:
        rebaixar("media", "Faltam informações para aplicar a política")

    if c.pedido_id and not pedido:
        rebaixar("media", f"Pedido {c.pedido_id} não encontrado na API")
    elif pedido:
        sinais.append(f"Dados do pedido {pedido['id']} verificados na API")
    if decisao.resultado in _DECISOES_FINANCEIRAS and not pedido:
        rebaixar("media", "Decisão financeira baseada só no relato: confirmar o pedido na API antes de executar")

    ids_recuperados = {t.id for t in trechos}
    if decisao.evidencias and not ids_recuperados & set(decisao.evidencias):
        rebaixar("media", "A busca não recuperou nenhuma das políticas usadas pela regra")

    return Confianca(nivel=nivel, sinais=sinais)


def acoes_fallback(confianca: Confianca, decisao: Decisao) -> list[str]:
    if confianca.nivel == "alta":
        return ["Executar somente após confirmação explícita do colaborador (nenhuma ação automática)."]

    acoes: list[str] = []
    if confianca.nivel == "media":
        acoes.append("Coletar as informações que faltam antes de recomendar qualquer ação.")
    else:
        acoes.append("Solicitar validação manual (supervisor ou especialista).")
        acoes.append("Orientar abertura de ticket interno com o contexto já levantado (Fluxo Suporte).")
    if decisao.resultado == Resultado.ANTIFRAUDE:
        acoes.append("Sinalizar a equipe antifraude e aplicar bloqueio preventivo (Fluxo Segurança).")
    acoes.append(f"Fornecer link de suporte, pois a confiança não é alta (Fluxo Suporte): {LINK_SUPORTE}")
    return acoes
