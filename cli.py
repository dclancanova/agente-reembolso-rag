"""Uso:
    python cli.py "O cliente quer reembolso, mas o pedido já saiu para entrega. Ainda é permitido?"
    python cli.py --cenarios          # roda todos os cenários de teste
    python cli.py --offline "..."     # força o modo sem LLM
"""
import argparse
import sys

from agente import AgenteReembolso
from cenarios import CENARIOS


def imprimir(r) -> None:
    print("=" * 90)
    print(f"PERGUNTA : {r.pergunta}")
    c = r.classificacao
    print(f"ENTENDEU : intenção={c.intencao} causa={c.causa} status={c.status_relatado} pedido={c.pedido_id}")
    print("BUSCA    : " + ", ".join(f"#{t.id}({t.score:.2f})" for t in r.trechos_recuperados))
    print(f"REGRA    : {r.decisao.regra} → {r.decisao.resultado.value}")
    print(f"CONFIANÇA: {r.confianca.nivel.upper()} | " + " | ".join(r.confianca.sinais))
    print(f"MODO     : {r.modo}")
    print("-" * 90)
    print(r.resposta)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="POC: agente interno de reembolso/cancelamento com RAG")
    p.add_argument("pergunta", nargs="?")
    p.add_argument("--cenarios", action="store_true")
    p.add_argument("--offline", action="store_true")
    a = p.parse_args()

    agente = AgenteReembolso(usar_claude=False if a.offline else None)
    print(f"Modo: {agente.modo} | Busca: {agente.base.backend} | {len(agente.base.trechos)} trechos indexados")

    if a.cenarios:
        for pergunta, *_ in CENARIOS:
            imprimir(agente.responder(pergunta))
    elif a.pergunta:
        imprimir(agente.responder(a.pergunta))
    else:
        p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
