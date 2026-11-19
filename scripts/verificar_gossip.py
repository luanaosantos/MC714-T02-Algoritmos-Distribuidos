"""Teste ponta a ponta contra os três contêineres já iniciados."""

import argparse
import json
import math
import sys
import time
import uuid
from urllib.request import ProxyHandler, Request, build_opener


def requisitar(base, rota, dados=None):
    corpo = None if dados is None else json.dumps(dados).encode("utf-8")
    pedido = Request(base + rota, data=corpo,
                     headers={"Content-Type": "application/json"})
    cliente = build_opener(ProxyHandler({}))
    with cliente.open(pedido, timeout=3) as resposta:
        return json.load(resposta)


def esperar_versao(urls, chave, esperado, timeout):
    limite = time.monotonic() + timeout
    observados = {}
    while time.monotonic() < limite:
        observados = {}
        for base in urls:
            try:
                observados[base] = requisitar(base, "/catalog").get(chave)
            except (OSError, ValueError) as erro:
                observados[base] = {"erro": str(erro)}
        if all(registro == esperado for registro in observados.values()):
            return
        time.sleep(0.1)
    raise RuntimeError("Convergência não observada no prazo: "
                       + json.dumps(observados, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", nargs=3, default=[
        "http://127.0.0.1:8001", "http://127.0.0.1:8002", "http://127.0.0.1:8003",
    ])
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout deve ser finito e positivo")
    try:
        for base in args.urls:
            saude = requisitar(base, "/health")
            if saude.get("status") != "ok":
                raise RuntimeError(f"Nó sem saúde: {base}")
        chave = "teste-gossip-" + uuid.uuid4().hex[:12]
        for i, valor in enumerate(("disponivel", "reservado", None)):
            resposta = requisitar(args.urls[i], "/put", {"chave": chave, "valor": valor})
            esperar_versao(args.urls, chave, resposta["registro"], args.timeout)
            operacao = ("escrita", "atualização", "remoção versionada")[i]
            print(f"PASS: {operacao} do nó {i + 1} propagou para os três nós.")
        print("GOSSIP VERIFICADO: três etapas convergiram sem /sync manual.")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as erro:
        print(f"FAIL: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
