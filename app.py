"""Interface de demonstração: streamlit run app.py"""
import streamlit as st

from agente import AgenteReembolso
from cenarios import CENARIOS

st.set_page_config(page_title="Agente de Reembolso (POC)", page_icon="🧾", layout="wide")

COR = {"alta": "green", "media": "orange", "baixa": "red"}
ROTULO = {"alta": "ALTA", "media": "MÉDIA", "baixa": "BAIXA"}


@st.cache_resource
def carregar(usar_claude: bool) -> AgenteReembolso:
    return AgenteReembolso(usar_claude=usar_claude)


with st.sidebar:
    st.header("Configuração")
    from agente import llm

    pode_claude = llm.disponivel()
    usar_claude = st.toggle("Usar Claude (entendimento + redação)", value=pode_claude, disabled=not pode_claude,
                            help="Requer ANTHROPIC_API_KEY. Sem chave, roda 100% offline.")
    agente = carregar(usar_claude)
    st.caption(f"Modo: **{agente.modo}** · Busca: **{agente.base.backend}** · "
               f"{len(agente.base.trechos)} trechos indexados")
    st.divider()
    st.subheader("Cenários de teste")
    for pergunta, *_ in CENARIOS:
        if st.button(pergunta, use_container_width=True):
            st.session_state.pergunta = pergunta

st.title("🧾 Agente interno de reembolsos e cancelamentos")
st.caption("POC com RAG + motor de regras + fallback seguro. Base simulada para fins educacionais; "
           "não representa políticas oficiais.")

pergunta = st.text_area("Pergunta do colaborador", key="pergunta", height=80,
                        placeholder="Ex.: Pedido 1003 saiu para entrega e o entregador extraviou o pedido.")

if st.button("Consultar agente", type="primary") and pergunta.strip():
    r = agente.responder(pergunta.strip())

    c1, c2, c3 = st.columns(3)
    c1.metric("Decisão", r.decisao.resultado.value.replace("_", " "))
    c2.markdown(f"**Confiança**\n\n:{COR[r.confianca.nivel]}[● {ROTULO[r.confianca.nivel]}]")
    c3.metric("Regra aplicada", r.decisao.regra)

    st.subheader("Resposta ao colaborador")
    st.markdown(r.resposta)
    if "avisos" in r.modo:
        st.warning(r.modo)

    st.subheader("Raciocínio auditável")
    a, b = st.columns(2)
    with a:
        st.markdown("**1. Entendimento**")
        st.json(r.classificacao.model_dump())
        st.markdown("**2a. API de pedidos (fatos)**")
        st.json(r.pedido or {"pedido": "não informado ou não encontrado"})
    with b:
        st.markdown("**2b. Busca na base (RAG)**")
        st.dataframe(
            [{"id": t.id, "score": t.score, "fonte": t.fonte, "pergunta": t.pergunta}
             for t in r.trechos_recuperados],
            hide_index=True, use_container_width=True,
        )
        st.markdown("**3. Evidências usadas pela regra:** " + ", ".join(f"#{i}" for i in r.decisao.evidencias))
        st.markdown("**4. Sinais de confiança**")
        for s in r.confianca.sinais:
            st.markdown(f"- {s}")
