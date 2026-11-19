"""Campanhas independentes: três algoritmos, três níveis, normal e crash."""

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError

from scripts.check_logs import auditar
from scripts.runtime import Cluster, esperar, digest_codigo, recuperar_compose_interrompido


def timeout_convergencia(resultado):
    return (resultado.get('algoritmo') == 'gossip' and not resultado.get('ok')
            and bool(resultado.get('amostras_ms'))
            and resultado.get('erro') == 'Condição não observada no prazo.')


def aguardar_detector_pronto(c, timeout=10):
    """Não contabilizar uma suspeita anterior como detecção do crash injetado."""
    esperar(lambda: all(not c.chamar(nome, '/state')['suspeitos'] for nome in c.nomes), timeout)


def validar_inicio_crash(c, alvo, vivos):
    if any(alvo in c.chamar(nome, '/state')['suspeitos'] for nome in vivos):
        raise ValueError('Suspeita ativa antes de iniciar o crash; detecção não pode ser medida neste ensaio.')


def injetar_crash(c, alvo, vivos, medir_heartbeat=False):
    if medir_heartbeat:
        aguardar_detector_pronto(c)
        validar_inicio_crash(c, alvo, vivos)
    inicio = c.registrar('crash_inicio', alvo=alvo)
    confirmado = c.matar(alvo)
    return inicio, confirmado


def marcar(c, rotulo, nomes):
    for nome in nomes:
        c.chamar(nome, "/event", {"rotulo": rotulo})


def coletar_trafego(pasta):
    envios = 0
    bytes_json = 0
    falsas = 0
    for p in Path(pasta).glob("no-*/logs/events.jsonl"):
        ativo = False
        for linha in p.read_text().splitlines():
            ev = json.loads(linha)
            if ev.get("rotulo") == "medicao_inicio":
                ativo = True
            if ev.get("rotulo") == "medicao_fim":
                ativo = False
            if ativo and ev["evento"] == "envio":
                envios += 1
                bytes_json += ev.get("bytes", 0)
            if ativo and ev["evento"] == "suspeito":
                falsas += 1
    return envios, bytes_json, falsas


def ensaio(pasta, base, algoritmo, nivel, falha, perfil):
    config = dict(base)
    config.update(gossip=algoritmo == "gossip", heartbeat=algoritmo == "heartbeat")
    if algoritmo == "lamport":
        config["nodes"] = nivel
    elif algoritmo == "gossip":
        config["gossip_interval"] = nivel
    else:
        config["heartbeat_timeout"] = nivel
    config["warmup"] = perfil["warmup"]
    cluster = Cluster(pasta, config)
    resultado = {"algoritmo": algoritmo, "nivel": nivel,
                 "cenario": "crash" if falha else "normal", "ok": False,
                 "amostras_ms": [], "run_id": cluster.run_id,
                 "seed": config["seed"], "environment": config.get("ambiente", "local")}
    try:
        with cluster as c:
            time.sleep(perfil["warmup"])
            if algoritmo == 'heartbeat' and falha:
                aguardar_detector_pronto(c)
            marcar(c, "medicao_inicio", c.nomes)
            vivos = list(c.nomes)
            if falha:
                vivo_morto = vivos.pop()
                inicio_crash, confirmado = injetar_crash(c, vivo_morto, vivos, algoritmo == 'heartbeat')
                instante_crash = inicio_crash
                resultado['confirmacao_crash_ms'] = (confirmado - inicio_crash) / 1e6
                if algoritmo == 'heartbeat':
                    resultado['metrica'] = 'inicio_da_injecao_ate_suspeita_observada_ms'
            inicio = time.monotonic()
            if algoritmo == "lamport":
                if falha:
                    try:
                        c.chamar(vivos[0], "/send", {"destino": vivo_morto, "conteudo": "falha"})
                        raise AssertionError("Destino parado confirmou uma mensagem.")
                    except HTTPError as erro:
                        if erro.code != 502:
                            raise
                for i in range(perfil["operations"]):
                    origem = vivos[i % len(vivos)]
                    destino = vivos[(i + 1) % len(vivos)]
                    t = time.monotonic_ns()
                    r = c.chamar(origem, "/send", {"destino": destino, "conteudo": f"m-{i}"})
                    resultado["amostras_ms"].append((time.monotonic_ns() - t) / 1e6)
                    if not (r["mensagem"]["marca"] < r["confirmacao"]["marca_recebimento"]
                            < r["confirmacao"]["marca_confirmacao"] < r["marca_retorno"]):
                        raise AssertionError("Ordem causal violada.")
            elif algoritmo == "gossip":
                for i in range(perfil["updates"]):
                    t = time.monotonic_ns()
                    chave = f"eq-{i}"
                    registro = c.chamar(vivos[i % len(vivos)], "/put",
                                         {"chave": chave, "valor": f"estado-{i}"})["registro"]
                    c.convergir(chave, registro, vivos, timeout=15)
                    resultado["amostras_ms"].append((time.monotonic_ns() - t) / 1e6)
            elif falha:
                pendentes = set(vivos)
                limite = time.monotonic() + nivel + 8
                while pendentes and time.monotonic() < limite:
                    for nome in list(pendentes):
                        if vivo_morto in c.chamar(nome, "/state")["suspeitos"]:
                            resultado["amostras_ms"].append((time.monotonic_ns() - instante_crash) / 1e6)
                            pendentes.remove(nome)
                    time.sleep(0.01)
                if pendentes:
                    raise TimeoutError("Detecção não observada em todos os sobreviventes.")
            else:
                # RTT heartbeat explícito, mais observação do detector em repouso.
                for i in range(perfil["heartbeat_samples"]):
                    t = time.monotonic_ns()
                    c.chamar(vivos[0], "/sync-heartbeat", {"destino": vivos[1]})
                    resultado["amostras_ms"].append((time.monotonic_ns() - t) / 1e6)
                time.sleep(perfil["normal_duration"])
            resultado["duracao_medida_s"] = time.monotonic() - inicio
            resultado["nos_observados"] = vivos
            marcar(c, "medicao_fim", vivos)
        resultado["auditoria"] = auditar(pasta)
        resultado["envios"], resultado["bytes_json"], suspeitas = coletar_trafego(pasta)
        if algoritmo == "heartbeat" and not falha:
            resultado["falsas_suspeitas"] = suspeitas
            resultado["falsas_por_no_minuto"] = suspeitas * 60 / (
                len(cluster.nomes) * resultado["duracao_medida_s"])
        resultado["ok"] = resultado["auditoria"]["ok"] and bool(resultado["amostras_ms"])
    except Exception as erro:
        resultado["erro"] = str(erro)
    cluster.gravar_json("trial.json", resultado)
    return resultado


def executar_campanha(perfil, base, saida, retomar=False, limite=None, aceitar_timeouts=False):
    saida = Path(saida)
    manifesto = {"perfil": perfil, "runtime": base, "source_sha256": digest_codigo()}
    if retomar:
        existente = json.loads((saida / "campaign.json").read_text())
        if existente != manifesto:
            raise ValueError("Fonte/perfil/runtime mudou; use uma nova campanha.")
    else:
        saida.mkdir(parents=True, exist_ok=False)
        (saida / "campaign.json").write_text(json.dumps(manifesto, indent=2))
    resumo = []
    executados = 0
    completa = True
    for algoritmo, niveis in perfil["levels"].items():
        for nivel in niveis:
            for falha in (False, True):
                for repeticao in range(perfil["repetitions"]):
                    nome = f"{algoritmo}-{nivel}-{'crash' if falha else 'normal'}-r{repeticao}"
                    pasta = saida / nome
                    config = {**base, "seed": perfil["seed"] + repeticao}
                    if (pasta / 'trial.json').exists():
                        resultado = json.loads((pasta / 'trial.json').read_text())
                        meta = json.loads((pasta / 'metadata.json').read_text())
                        aceito = resultado.get('ok') or (aceitar_timeouts and timeout_convergencia(resultado))
                        if (not aceito or resultado.get('run_id') != nome
                                or resultado.get('algoritmo') != algoritmo or resultado.get('nivel') != nivel
                                or resultado.get('cenario') != ('crash' if falha else 'normal')
                                or resultado.get('seed') != config['seed']
                                or meta.get('source_sha256') != manifesto['source_sha256']
                                or not auditar(pasta)['ok']):
                            raise ValueError(f'Evidência inválida em {nome}; não será ignorada ou sobrescrita.')
                        resumo.append(resultado)
                        continue
                    if limite is not None and executados >= limite:
                        completa = False
                        continue
                    if pasta.exists():
                        if (pasta / 'compose.run.json').exists():
                            recuperar_compose_interrompido(pasta)
                        arquivo = saida / 'interrupted' / f'{nome}-{time.time_ns()}'
                        arquivo.parent.mkdir(exist_ok=True)
                        pasta.rename(arquivo)
                    resultado = ensaio(pasta, config, algoritmo, nivel, falha, perfil)
                    executados += 1
                    resumo.append(resultado)
                    print(f"{'PASS' if resultado['ok'] else 'FAIL'} {nome}", flush=True)
    (saida / "campaign-verdict.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2))
    timeouts = sum(timeout_convergencia(r) and auditar(saida/r['run_id'])['ok'] for r in resumo)
    aprovados = sum(r['ok'] for r in resumo)
    estado = {'completa': completa, 'executados_neste_lote': executados,
              'concluidos': len(resumo), 'ok': aprovados == len(resumo),
              'aprovados': aprovados, 'timeouts': timeouts,
              'integridade_ok': aprovados + timeouts == len(resumo)}
    (saida / 'campaign-progress.json').write_text(json.dumps(estado, indent=2))
    return estado


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/experiments-fast.json")
    parser.add_argument("--runtime", default="configs/local.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action='store_true')
    parser.add_argument("--max-trials", type=int)
    parser.add_argument('--allow-timeouts', action='store_true',
                        help='Continuar após timeout de gossip auditado; preserva a ocorrência e exclui amostras parciais da análise.')
    args = parser.parse_args()
    if args.max_trials is not None and args.max_trials < 1:
        parser.error('--max-trials deve ser positivo.')
    perfil = json.loads(Path(args.config).read_text())
    base = json.loads(Path(args.runtime).read_text())
    estado = executar_campanha(perfil, base, args.output, args.resume, args.max_trials, args.allow_timeouts)
    print(json.dumps(estado, ensure_ascii=False), flush=True)
    aceito = estado['ok'] or (args.allow_timeouts and estado['integridade_ok'])
    return 0 if aceito and estado['completa'] else (3 if aceito else 1)


if __name__ == "__main__":
    raise SystemExit(main())
