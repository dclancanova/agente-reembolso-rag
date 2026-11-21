"""Testes determinísticos (modo offline): decisão, confiança e grounding."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente import AgenteReembolso  # noqa: E402
from agente.redator import validar_resposta_llm  # noqa: E402
from cenarios import CENARIOS  # noqa: E402


@pytest.fixture(scope="module", params=[False, True], ids=["lexical", "hibrido"])
def agente(request):
    a = AgenteReembolso(usar_claude=False, usar_embeddings=request.param, log=None)
    if request.param and a.base.backend.startswith("lexical"):
        pytest.skip("fastembed indisponível")
    return a


@pytest.mark.parametrize("pergunta,resultado,nivel", CENARIOS, ids=[c[0][:45] for c in CENARIOS])
def test_cenario(agente, pergunta, resultado, nivel):
    r = agente.responder(pergunta)
    assert r.decisao.resultado.value == resultado, r.decisao.regra
    assert r.confianca.nivel == nivel, r.confianca.sinais


def test_cenario_principal_diferencia_as_quatro_causas(agente):
    r = agente.responder("O cliente quer reembolso, mas o pedido já saiu para entrega. Ainda é permitido?")
    texto = r.resposta.lower()
    for termo in ["restaurante", "app", "entregador", "desistência"]:
        assert termo in texto
    assert {2, 18, 9} <= set(r.decisao.evidencias)
    assert any("link de suporte" in a.lower() for a in r.acoes_fallback)


def test_busca_recupera_politica_de_despacho(agente):
    ids = [t.id for t in agente.base.buscar("pedido já despachado, cliente quer o dinheiro de volta")]
    assert {2, 18} & set(ids)


def test_toda_evidencia_existe_na_base(agente):
    for pergunta, *_ in CENARIOS:
        r = agente.responder(pergunta)
        assert len(agente.base.por_ids(r.decisao.evidencias)) == len(r.decisao.evidencias)


def test_baixa_confianca_sempre_tem_ticket_e_link(agente):
    for pergunta, _, nivel in CENARIOS:
        if nivel == "baixa":
            acoes = " ".join(agente.responder(pergunta).acoes_fallback).lower()
            assert "ticket" in acoes and "link de suporte" in acoes


class _ClaudeFalso:
    """Simula o LLM para testar validação e degradação sem chamar a API."""

    def __init__(self, resposta=None, erro=False):
        self.resposta, self.erro = resposta, erro

    def classificar(self, pergunta):
        if self.erro:
            raise ConnectionError("API fora do ar")
        return None  # força o classificador offline

    def redigir(self, *args):
        if self.erro:
            raise ConnectionError("API fora do ar")
        return self.resposta


def test_resposta_do_llm_com_alucinacao_e_descartada():
    a = AgenteReembolso(usar_claude=False, usar_embeddings=False, log=None)
    a.claude = _ClaudeFalso("Reembolso aprovado em 7 dias [#99] conforme Política 9.9.")
    r = a.responder("Pedido 1003 já saiu para entrega e o entregador extraviou o pedido.")
    assert "reprovada na validação" in r.modo
    assert "[#13]" in r.resposta  # caiu para a redação determinística


def test_resposta_do_llm_fundamentada_e_aceita():
    a = AgenteReembolso(usar_claude=False, usar_embeddings=False, log=None)
    a.claude = _ClaudeFalso("Recomendação: reembolso total de R$ 41,00 [#13] (Política 2.2).")
    r = a.responder("Pedido 1003 já saiu para entrega e o entregador extraviou o pedido.")
    assert r.resposta.startswith("Recomendação: reembolso total")
    assert "avisos" not in r.modo


def test_api_do_llm_fora_do_ar_degrada_para_offline():
    a = AgenteReembolso(usar_claude=False, usar_embeddings=False, log=None)
    a.claude = _ClaudeFalso(erro=True)
    r = a.responder("Pedido 1001 saiu para entrega e o cliente desistiu, quer reembolso.")
    assert r.decisao.resultado.value == "validacao_manual"
    assert "falhou" in r.modo


def test_validacao_reprova_citacao_inventada():
    pedido = {"valor": 41.0}
    ok = "Reembolso total [#13] (Política 2.2), valor R$ 41,00."
    assert validar_resposta_llm(ok, {13}, {"Política 2.2"}, pedido) == []
    ruim = "Reembolso em até 7 dias [#99] (Política 9.9), valor R$ 50,00."
    problemas = validar_resposta_llm(ruim, {13}, {"Política 2.2"}, pedido)
    assert len(problemas) == 3
