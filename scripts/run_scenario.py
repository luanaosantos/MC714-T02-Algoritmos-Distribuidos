"""Cenários reproduzíveis, com veredito e auditoria dos logs."""

import argparse
import json
import time
from pathlib import Path

from scripts.check_logs import auditar
from scripts.runtime import Cluster, esperar

CENARIOS = ("normal", "crash", "restart", "partition", "delay_loss", "combined")


def executar(c, cenario):
    if cenario not in CENARIOS:
        raise ValueError("Cenário desconhecido.")
    time.sleep(c.config.get("warmup", 0.25))
    nomes = c.nomes
    chave = "equipamento-17"
    inicial = c.chamar(nomes[0], "/put", {"chave": chave, "valor": "disponivel"})["registro"]
    c.convergir(chave, inicial)
    c.registrar("convergencia_inicial")
    alvo = nomes[-1]
    if cenario == "normal":
        for i, nome in enumerate(nomes):
            c.chamar(nome, "/send", {"destino": nomes[(i + 1) % len(nomes)], "conteudo": "teste"})
        esperar(lambda: all(not c.chamar(n, "/state")["suspeitos"] for n in nomes), 5)
    elif cenario in ("crash", "restart"):
        c.matar(alvo)
        vivos = nomes[:-1]
        esperar(lambda: all(alvo in c.chamar(n, "/state")["suspeitos"] for n in vivos),
                c.config.get("heartbeat_timeout", 0.6) + 5)
        atualizado = c.chamar(nomes[0], "/put", {"chave": chave, "valor": "reservado"})["registro"]
        c.convergir(chave, atualizado, vivos)
        if cenario == "restart":
            c.reiniciar(alvo)
            c.convergir(chave, atualizado)
            esperar(lambda: all(alvo not in c.chamar(n, "/state")["suspeitos"] for n in vivos), 5)
            restaurado = c.chamar(alvo, "/put", {"chave": chave, "valor": "manutencao"})["registro"]
            if restaurado["contador"] <= atualizado["contador"]:
                raise AssertionError("Reinício regrediu versão.")
            c.convergir(chave, restaurado)
    elif cenario in ("partition", "combined"):
        c.particao()
        if cenario == "combined":
            c.matar(alvo)
        l = c.chamar(nomes[0], "/put", {"chave": chave, "valor": "grupo-a"})["registro"]
        r = c.chamar(nomes[len(nomes)//2], "/put", {"chave": chave, "valor": "grupo-b"})["registro"]
        if cenario == "combined":
            c.reiniciar(alvo)
        time.sleep(c.config.get("heartbeat_timeout", 0.6) + 0.15)
        c.gravar_json("durante_particao.json", {n: c.chamar(n, "/catalog") for n in nomes})
        c.curar()
        vencedor = max((l, r), key=lambda x: (x["contador"], x["origem"]))
        c.convergir(chave, vencedor)
        esperar(lambda: all(not c.chamar(n, "/state")["suspeitos"] for n in nomes), 5)
    elif cenario == "delay_loss":
        for nome in nomes:
            c.regras(nome, {"atraso_ms": 20, "perda": 0.2, "duplicacao": 0.3})
        atualizado = c.chamar(nomes[0], "/put", {"chave": chave, "valor": "rede-instavel"})["registro"]
        c.convergir(chave, atualizado, timeout=10)
        c.curar()
        c.convergir(chave, atualizado)
    snapshots = {}
    for nome in nomes:
        if cenario == "crash" and nome == alvo:
            continue
        snapshots[nome] = c.chamar(nome, "/catalog")
    c.gravar_json("snapshots_finais.json", snapshots)
    if len({json.dumps(x, sort_keys=True) for x in snapshots.values()}) != 1:
        raise AssertionError("Réplicas finais divergentes.")


def rodar(pasta, config, cenario):
    inicio = time.monotonic()
    resultado = {"cenario": cenario, "ok": False}
    cluster = Cluster(pasta, config)
    try:
        with cluster:
            executar(cluster, cenario)
        resultado["auditoria"] = auditar(pasta)
        resultado["ok"] = resultado["auditoria"]["ok"]
    except Exception as erro:
        resultado["erro"] = str(erro)
    resultado["duracao_s"] = time.monotonic() - inicio
    cluster.gravar_json("verdict.json", resultado)
    return resultado


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=CENARIOS, default="normal")
    parser.add_argument("--config", default="configs/local.json")
    parser.add_argument("--output")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    pasta = args.output or f"results/raw/scenario-{args.scenario}-{time.time_ns()}"
    resultado = rodar(pasta, config, args.scenario)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    print(f"Dados: {pasta}")
    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
