"""Motor de regras: a decisão é determinística, testável e auditável.

O LLM NUNCA decide elegibilidade. Ele só entende a pergunta e explica a decisão.
Cada regra aponta para os registros da base (IDs) que a sustentam.

Precedência: risco (fraude, não autorizado, divergência) > fatos do sistema > causa > dúvida geral.
"""
from __future__ import annotations

from typing import Optional

from .api_pedidos import LIMITE_REEMBOLSOS_30D
from .modelos import Classificacao, Decisao, Resultado, Trecho

TEXTO_CAUSAS = (
    "Após a saída para entrega, a decisão depende de quem causou o problema: "
    "erro do restaurante → reembolso total (Política 2.1); erro do app → reembolso total, salvo fraude "
    "(Política 2.1); falha do entregador (extravio ou entrega incorreta) → elegível (Política 2.2); "
    "desistência do cliente → pode não ser elegível (Políticas 3.2 e 4.1), exige análise manual."
)


def decidir(c: Classificacao, pedido: Optional[dict], trechos: list[Trecho], limiar: float) -> Decisao:
    status = pedido["status"] if pedido else c.status_relatado
    causa_sistema = pedido.get("causa_registrada") if pedido else None
    causa = causa_sistema if causa_sistema and causa_sistema != "indefinida" else c.causa
    saiu = status in ("saiu_para_entrega", "entregue")

    # ---------- 1. Risco: sempre avaliado primeiro ----------
    reembolsos = pedido.get("reembolsos_cliente_30d", 0) if pedido else 0
    if c.suspeita_fraude or (pedido and pedido.get("alerta_fraude")) or reembolsos > LIMITE_REEMBOLSOS_30D:
        motivo = "alerta de fraude no sistema" if pedido and pedido.get("alerta_fraude") else (
            f"{reembolsos} reembolsos nos últimos 30 dias" if reembolsos > LIMITE_REEMBOLSOS_30D
            else "suspeita de fraude relatada")
        return Decisao(
            resultado=Resultado.ANTIFRAUDE, regra="R01_fraude", requer_humano=True, evidencias=[19, 20],
            explicacao=f"Sinal de risco ({motivo}). O Fluxo Segurança manda encaminhar para avaliação manual, "
                       "bloqueio preventivo e sinalizar a equipe antifraude. Nenhum reembolso deve ser executado.",
        )

    if c.nao_autorizado:
        return Decisao(
            resultado=Resultado.VALIDACAO_MANUAL, regra="R02_nao_autorizado", requer_humano=True,
            evidencias=[10, 11],
            explicacao="O cliente afirma não ter autorizado o pedido. A Política 4.4 exige avaliação manual e "
                       "possível abertura de ticket interno.",
        )

    if c.consta_entregue_nao_chegou or (pedido and pedido.get("ocorrencia") == "cliente_relata_nao_recebimento"):
        return Decisao(
            resultado=Resultado.VALIDACAO_MANUAL, regra="R03_consta_entregue", requer_humano=True,
            evidencias=[14, 11],
            explicacao="O pedido consta como entregue, mas o cliente diz que não recebeu. O Fluxo de Entrega "
                       "orienta validação manual, com possível reembolso após análise.",
        )

    if pedido and pedido["status"] == "cancelado" and pedido["pagamento"]["status"] == "cobrado":
        return Decisao(
            resultado=Resultado.VALIDACAO_MANUAL, regra="R04_divergencia_financeira", requer_humano=True,
            evidencias=[11, 6],
            explicacao="O pedido está cancelado, mas o pagamento aparece como cobrado, sem estorno. Há divergência "
                       "entre status financeiro e status do pedido: o Fluxo Suporte manda orientar ticket.",
        )

    if c.cobranca_duplicada:
        return Decisao(
            resultado=Resultado.VALIDACAO_MANUAL, regra="R05_cobranca_duplicada", requer_humano=True,
            evidencias=[7],
            explicacao="Cobrança em duplicidade não é esperada. O Fluxo Financeiro manda abrir ticket para "
                       "validação financeira.",
        )

    if c.cobranca_apos_cancelamento:
        return Decisao(
            resultado=Resultado.VERIFICAR_ESTORNO, regra="R06_cobranca_apos_cancelamento", requer_humano=False,
            evidencias=[6, 11],
            explicacao="É preciso validar o status do estorno. Dependendo do meio de pagamento, a devolução pode "
                       "levar até 14 dias (Fluxo Financeiro). Se o estorno não existir ou divergir do status do "
                       "pedido, abrir ticket (Fluxo Suporte).",
            perguntas=[] if pedido else ["Qual o número do pedido, para consultar o status do estorno na API?"],
        )

    if causa_sistema and causa_sistema != "indefinida" and c.causa != "indefinida" and c.causa != causa_sistema:
        return Decisao(
            resultado=Resultado.VALIDACAO_MANUAL, regra="R07_conflito_relato_sistema", requer_humano=True,
            evidencias=[11],
            explicacao=f"O relato aponta causa '{c.causa}', mas o sistema registra '{causa_sistema}'. "
                       "Com fontes divergentes, a política não é clara para este caso: orientar ticket.",
        )

    # ---------- 2. Decisão pela causa ----------
    ev_despacho = [2, 18] if saiu else []

    if causa == "restaurante":
        return Decisao(
            resultado=Resultado.REEMBOLSO_TOTAL, regra="R10_falha_restaurante", requer_humano=False,
            evidencias=ev_despacho + [3, 1] + ([] if saiu else [4, 5]),
            explicacao="Falha do restaurante gera reembolso total (Políticas 2.1 e 3.2), inclusive após o despacho, "
                       "porque o erro não é do cliente. Para falta de item ou ingrediente, o reembolso é automático, "
                       "salvo exceções operacionais específicas (Política 2.3).",
        )

    if causa == "app":
        return Decisao(
            resultado=Resultado.REEMBOLSO_TOTAL, regra="R11_erro_app", requer_humano=False,
            evidencias=ev_despacho + [17],
            explicacao="Erro do app gera reembolso total, salvo fraude (Política 2.1). Sinais de fraude já foram "
                       "verificados antes desta regra.",
        )

    if causa == "entregador":
        return Decisao(
            resultado=Resultado.REEMBOLSO_TOTAL, regra="R12_falha_entregador", requer_humano=False,
            evidencias=ev_despacho + [13, 1],
            explicacao="Falha do entregador (extravio ou entrega incorreta) é elegível (Política 2.2). Erro "
                       "comprovado na entrega gera reembolso total (Política 3.2).",
        )

    if causa == "cliente":
        if status == "aguardando_preparo":
            return Decisao(
                resultado=Resultado.ESTORNO_AUTOMATICO, regra="R13a_cliente_antes_preparo", requer_humano=False,
                evidencias=[8],
                explicacao="Cancelamento antes da preparação do pedido tem estorno automático (Política 3.5).",
            )
        if saiu:
            return Decisao(
                resultado=Resultado.VALIDACAO_MANUAL, regra="R13b_desistencia_apos_despacho", requer_humano=True,
                evidencias=[2, 9, 18, 11],
                explicacao="Desistência do cliente após a saída para entrega 'pode não ser elegível' (Políticas "
                           "3.2 e 4.1). A política não é conclusiva, então o agente não aprova nem nega: "
                           "orienta ticket (Fluxo Suporte).",
            )
        if status == "em_preparo":
            return Decisao(
                resultado=Resultado.VALIDACAO_MANUAL, regra="R13c_cliente_em_preparo", requer_humano=True,
                evidencias=[8, 11],
                explicacao="O estorno automático só cobre cancelamento antes da preparação (Política 3.5). "
                           "A base não define o caso com o pedido já em preparo: orientar ticket.",
            )
        return Decisao(
            resultado=Resultado.PEDIR_INFORMACAO, regra="R13d_cliente_status_desconhecido", requer_humano=False,
            evidencias=[8, 2],
            explicacao="Para desistência do cliente, a decisão depende do momento: antes do preparo há estorno "
                       "automático (Política 3.5); após o despacho pode não ser elegível (Política 3.2).",
            perguntas=["Qual o número do pedido ou o status atual (antes do preparo, em preparo, saiu para entrega)?"],
        )

    # ---------- 3. Causa indefinida ----------
    if saiu:
        return Decisao(
            resultado=Resultado.PEDIR_INFORMACAO, regra="R14_despacho_causa_indefinida", requer_humano=False,
            evidencias=[2, 18, 9, 3, 17, 13],
            explicacao=TEXTO_CAUSAS,
            perguntas=["O que motivou o pedido de reembolso: erro do restaurante, erro do app, falha do entregador "
                       "ou desistência do cliente?",
                       "Qual o número do pedido, para validar status e ocorrência na API?"],
        )

    relevantes = [t.id for t in trechos if t.score >= limiar]
    pergunta_geral = not c.pedido_id and status == "desconhecido"

    if c.intencao in ("reembolso", "cancelamento") and not (pergunta_geral and relevantes):
        return Decisao(
            resultado=Resultado.PEDIR_INFORMACAO, regra="R15_dados_insuficientes", requer_humano=False,
            evidencias=[1],
            explicacao="Reembolso total cabe quando o restaurante cancela ou há erro comprovado na entrega "
                       "(Política 3.2). Sem o motivo e o status do pedido, não há como aplicar a política.",
            perguntas=["Qual o número do pedido?", "Qual o motivo do cancelamento ou reembolso?"],
        )

    # ---------- 4. Dúvida sobre política: resposta vem da base (RAG) ----------
    if relevantes and c.intencao != "fora_do_escopo":
        topo = trechos[0].score
        proximos = [t.id for t in trechos if t.score >= max(limiar, topo - 0.08)]
        return Decisao(
            resultado=Resultado.ORIENTACAO, regra="R20_orientacao_politica", requer_humano=False,
            evidencias=proximos[:2],
            explicacao="Pergunta informativa sobre a política, respondida a partir dos trechos recuperados da base.",
        )

    return Decisao(
        resultado=Resultado.SEM_BASE, regra="R99_sem_cobertura", requer_humano=True, evidencias=[12, 11],
        explicacao="A base de conhecimento não cobre esta pergunta com segurança. Pelo Fluxo Suporte, o agente "
                   "não gera resposta incerta: orienta ticket e fornece link de suporte.",
    )
