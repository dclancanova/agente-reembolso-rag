"""Redação da resposta: modelo determinístico (offline) + validação da resposta do LLM."""
from __future__ import annotations

import re
from typing import Optional

from .modelos import Confianca, Decisao, Resultado, Trecho

TITULOS = {
    Resultado.REEMBOLSO_TOTAL: "Elegível para reembolso total",
    Resultado.ESTORNO_AUTOMATICO: "Estorno automático",
    Resultado.VERIFICAR_ESTORNO: "Verificar o status do estorno",
    Resultado.PEDIR_INFORMACAO: "Faltam informações para decidir",
    Resultado.VALIDACAO_MANUAL: "Não decidir: encaminhar para validação manual",
    Resultado.ANTIFRAUDE: "Não reembolsar: encaminhar para antifraude",
    Resultado.ORIENTACAO: "Orientação da política",
    Resultado.SEM_BASE: "Sem informação suficiente na base",
}


def redigir_modelo(decisao: Decisao, evidencias: list[Trecho], confianca: Confianca, acoes: list[str],
                   pedido: Optional[dict]) -> str:
    nivel = {"alta": "alta", "media": "média", "baixa": "baixa"}[confianca.nivel]
    linhas = [f"**Recomendação:** {TITULOS[decisao.resultado]} (confiança {nivel})."]
    if pedido:
        linhas.append(f"**Pedido {pedido['id']}:** status `{pedido['status']}`, ocorrência "
                      f"`{pedido['ocorrencia']}`, valor R$ {pedido['valor']:.2f}.")
    linhas.append(f"**Por quê:** {decisao.explicacao}")
    if decisao.resultado == Resultado.ORIENTACAO:
        for t in evidencias:
            linhas.append(f"- {t.resposta} [#{t.id} · {t.fonte}]")
    linhas.append("**Fontes consultadas:** " + "; ".join(f"[#{t.id}] {t.fonte}" for t in evidencias))
    if decisao.perguntas:
        linhas.append("**Perguntar ao colaborador:**\n" + "\n".join(f"- {p}" for p in decisao.perguntas))
    linhas.append("**Próximos passos:**\n" + "\n".join(f"- {a}" for a in acoes))
    return "\n\n".join(linhas)


def validar_resposta_llm(texto: str, ids_permitidos: set[int], fontes_permitidas: set[str],
                         pedido: Optional[dict]) -> list[str]:
    """Grounding: tudo o que o LLM cita precisa existir no contexto que ele recebeu."""
    problemas = []
    citados = {int(x) for x in re.findall(r"#(\d+)", texto)}
    if not citados:
        problemas.append("resposta sem citações da base")
    if extras := citados - ids_permitidos:
        problemas.append(f"cita trechos não fornecidos: {sorted(extras)}")
    for pol in set(re.findall(r"Pol[ií]tica\s+(\d+(?:\.\d+)?)", texto)):
        if not any(pol in f for f in fontes_permitidas):
            problemas.append(f"cita Política {pol}, que não está nos trechos")
    valores = {v.replace(".", "").replace(",", ".") for v in re.findall(r"R\$\s?([\d.]+,\d{2}|\d+(?:\.\d{2})?)", texto)}
    if valores:
        valor_pedido = f"{pedido['valor']:.2f}" if pedido else None
        if any(float(v) != float(valor_pedido or -1) for v in valores):
            problemas.append("menciona valor que não vem da API do pedido")
    return problemas
