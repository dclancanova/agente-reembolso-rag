"""Base de conhecimento + busca (o "R" do RAG).

Cada linha do CSV vira um chunk (pergunta + resposta já formam uma unidade completa).
O texto indexado é "categoria: pergunta resposta"; categoria e fonte ficam como metadados.

Busca híbrida:
  - lexical (TF-IDF de palavras + n-gramas de caracteres): sempre disponível, robusta
    a variações como "reembolso"/"reembolsável";
  - semântica (embeddings multilíngues via fastembed): usada se o pacote estiver instalado.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .modelos import Trecho

_ARQUIVO = Path(__file__).resolve().parent.parent / "data" / "base_conhecimento.csv"
_MODELO_EMBEDDING = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Vocabulário operacional que o colaborador usa x vocabulário da política.
SINONIMOS = {
    "despachado": "saiu para entrega despacho",
    "despachou": "saiu para entrega despacho",
    "a caminho": "saiu para entrega",
    "em rota": "saiu para entrega",
    "saiu para entrega": "despacho",
    "desistiu": "desistencia do cliente",
    "mudou de ideia": "desistencia do cliente",
    "nao quer mais": "desistencia do cliente",
    "estorno": "reembolso devolucao",
    "devolver o dinheiro": "reembolso estorno",
    "motoboy": "entregador",
    "extraviado": "extravio entregador",
    "cobrado de novo": "cobrado duas vezes",
    "falta de ingrediente": "falha do restaurante",
    "nao tinha o item": "restaurante nao tiver o item",
    "aguardando preparo": "antes da preparacao do pedido estorno automatico",
    "antes do preparo": "antes da preparacao do pedido estorno automatico",
}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()


def expandir_consulta(consulta: str) -> str:
    base = normalizar(consulta)
    extras = [v for k, v in SINONIMOS.items() if k in base]
    return " ".join([base, *extras])


class BaseConhecimento:
    def __init__(self, arquivo: Path = _ARQUIVO, usar_embeddings: bool = True):
        with open(arquivo, encoding="utf-8") as f:
            linhas = [r for r in csv.DictReader(f) if r.get("pergunta")]
        self.trechos = [
            Trecho(id=i, categoria=r["categoria"], pergunta=r["pergunta"],
                   resposta=r["resposta"], fonte=r["fonte"])
            for i, r in enumerate(linhas, start=1)
        ]
        self._por_id = {t.id: t for t in self.trechos}
        textos = [normalizar(f"{t.categoria}: {t.pergunta} {t.resposta}") for t in self.trechos]

        self._tfidf_palavras = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
        self._tfidf_chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self._m_palavras = self._tfidf_palavras.fit_transform(textos)
        self._m_chars = self._tfidf_chars.fit_transform(textos)

        self._embedder = None
        self._m_emb = None
        if usar_embeddings:
            self._carregar_embeddings(textos)

        # Abaixo deste score a base é considerada "sem cobertura" para a pergunta.
        self.limiar = 0.40 if self._embedder else 0.22

    @property
    def backend(self) -> str:
        return "híbrido (embeddings + TF-IDF)" if self._embedder else "lexical (TF-IDF)"

    def _carregar_embeddings(self, textos: list[str]) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError:
            return
        try:
            self._embedder = TextEmbedding(_MODELO_EMBEDDING)
            self._m_emb = np.array(list(self._embedder.embed(textos)))
        except Exception:  # sem rede para baixar o modelo, por exemplo
            self._embedder, self._m_emb = None, None

    def buscar(self, consulta: str, k: int = 4) -> list[Trecho]:
        q = expandir_consulta(consulta)
        lexical = 0.5 * cosine_similarity(self._tfidf_palavras.transform([q]), self._m_palavras)[0] \
            + 0.5 * cosine_similarity(self._tfidf_chars.transform([q]), self._m_chars)[0]
        if self._embedder is not None:
            v = np.array(list(self._embedder.embed([q])))
            semantico = cosine_similarity(v, self._m_emb)[0]
            scores = 0.6 * semantico + 0.4 * lexical
        else:
            scores = lexical
        ordem = np.argsort(-scores)[:k]
        return [self.trechos[i].model_copy(update={"score": round(float(scores[i]), 3)}) for i in ordem]

    def por_ids(self, ids: list[int]) -> list[Trecho]:
        return [self._por_id[i] for i in ids if i in self._por_id]

    def fontes(self, ids: Optional[list[int]] = None) -> set[str]:
        alvo = self.por_ids(ids) if ids else self.trechos
        return {t.fonte for t in alvo}
