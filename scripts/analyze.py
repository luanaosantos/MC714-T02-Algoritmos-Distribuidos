"""Regenera estatísticas, gráficos e comparação a partir de dados reais."""

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from scripts.check_logs import auditar
from scripts.run_experiments import timeout_convergencia


def percentil(valores, p):
    if not valores:
        raise ValueError("Amostra vazia.")
    ordem = sorted(valores)
    posicao = (len(ordem) - 1) * p
    inferior = math.floor(posicao)
    superior = math.ceil(posicao)
    return ordem[inferior] + (ordem[superior] - ordem[inferior]) * (posicao - inferior)



def verificar_matriz(entrada):
    """Detecta ensaios ausentes mesmo quando os arquivos existentes são válidos."""
    ausentes = []
    campanhas = [p for p in Path(entrada).rglob("campaign.json") if "source_snapshot" not in p.parts]
    if not campanhas:
        return [{"ausente": "campaign.json", "erro": "Matriz da campanha não encontrada."}]
    for arquivo in campanhas:
        try:
            perfil = json.loads(arquivo.read_text())["perfil"]
            repeticoes = perfil["repetitions"]
            if type(repeticoes) is not int or repeticoes < 2:
                raise ValueError("Campanha precisa de repetições independentes.")
            for algoritmo, niveis in perfil["levels"].items():
                if len(set(niveis)) < 3:
                    raise ValueError("São necessários três níveis distintos por algoritmo.")
                for nivel in niveis:
                    for cenario in ("normal", "crash"):
                        for repeticao in range(repeticoes):
                            nome = f"{algoritmo}-{nivel}-{cenario}-r{repeticao}"
                            if not (arquivo.parent / nome / "trial.json").is_file():
                                ausentes.append({"ausente": str(arquivo.parent / nome / "trial.json")})
        except (OSError, ValueError, KeyError, TypeError) as erro:
            ausentes.append({"ausente": str(arquivo), "erro": str(erro)})
    return ausentes


def falha_observada(resultado):
    """Falhas de medição conhecidas; não aceitar erros arbitrários como evidência válida."""
    if resultado.get('ok') or resultado.get('algoritmo') != 'heartbeat':
        return None
    if resultado.get('cenario') == 'normal' and resultado.get('erro') == 'timed out':
        return 'timeout_controle'
    if resultado.get('cenario') == 'crash' and resultado.get('erro') == (
            'Suspeita ativa antes de iniciar o crash; detecção não pode ser medida neste ensaio.'):
        return 'baseline_suspeita'
    return None


def analisar(entrada, saida):
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    grupos = defaultdict(list)
    tentativas = defaultdict(int)
    timeouts, falhas = [], []
    contagem_timeouts, contagem_falhas = defaultdict(int), defaultdict(int)
    invalidos = verificar_matriz(entrada)
    campanhas = {}
    for arquivo in sorted(Path(entrada).rglob('campaign.json')):
        if 'source_snapshot' in arquivo.parts:
            continue
        conteudo = json.loads(arquivo.read_text())
        identificador = str(arquivo.parent.resolve())
        campanhas[arquivo.parent.resolve()] = {'id': identificador, **conteudo}
        metadados = next(iter(sorted(arquivo.parent.glob('*/metadata.json'))), None)
        if metadados:
            campanhas[arquivo.parent.resolve()]['metadados'] = json.loads(metadados.read_text())
    for p in sorted(Path(entrada).rglob('trial.json')):
        if 'source_snapshot' in p.parts:
            continue
        try:
            r = json.loads(p.read_text())
            auditoria = auditar(p.parent)
            amostras = r.get('amostras_ms', [])
            timeout, falha = timeout_convergencia(r), falha_observada(r)
            if (r.get('run_id') != p.parent.name or not auditoria['ok']
                    or (not r.get('ok') and not timeout and not falha)
                    or (r.get('ok') and not amostras)
                    or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in amostras)):
                raise ValueError(r.get('erro') or 'Resultado/amostras/logs inválidos.')
            campanha = campanhas.get(p.parent.parent.resolve())
            if campanha is None:
                raise ValueError('Ensaio fora de uma campanha.')
            perfil = campanha['perfil']
            nomes = {f'{alg}-{nivel}-{cenario}-r{rep}'
                for alg, niveis in perfil['levels'].items() for nivel in niveis
                for cenario in ('normal', 'crash') for rep in range(perfil['repetitions'])}
            reps = [rep for rep in range(perfil['repetitions'])
                    if p.parent.name == f"{r['algoritmo']}-{r['nivel']}-{r['cenario']}-r{rep}"]
            ambiente = campanha.get('runtime', {}).get('ambiente', 'local')
            if p.parent.name not in nomes or len(reps) != 1 or r['environment'] != ambiente:
                raise ValueError('Campos do ensaio incompatíveis com pasta/perfil/ambiente.')
            if isinstance(campanha.get('source_sha256'), str):
                meta = json.loads((p.parent/'metadata.json').read_text())
                if meta.get('source_sha256') != campanha['source_sha256']:
                    raise ValueError('Fonte do ensaio diverge do manifesto da campanha.')
                if 'seed' in perfil and (r.get('seed') != perfil['seed'] + reps[0]
                        or meta.get('config', {}).get('seed') != r['seed']):
                    raise ValueError('Semente do ensaio diverge do perfil/metadados.')
            chave = (campanha['id'], r['environment'], r['algoritmo'], r['cenario'], r['nivel'])
            tentativas[chave] += 1
            if timeout or falha:
                item = {'arquivo': str(p), 'campanha': campanha['id'], 'algoritmo': r['algoritmo'],
                        'nivel': r['nivel'], 'cenario': r['cenario'], 'erro': r['erro'],
                        'amostras_parciais_excluidas': len(amostras), 'auditoria': auditoria}
                if timeout:
                    contagem_timeouts[chave] += 1
                    timeouts.append(item)
                else:
                    contagem_falhas[chave] += 1
                    falhas.append({**item, 'causa': falha})
            else:
                grupos[chave].append(r)
        except (OSError, ValueError, KeyError, TypeError) as erro:
            invalidos.append({'arquivo': str(p), 'erro': str(erro)})
    linhas = []
    for chave in sorted(tentativas):
        ensaios = grupos[chave]
        amostras = [x for r in ensaios for x in r['amostras_ms']]
        medianas = [statistics.median(r['amostras_ms']) for r in ensaios]
        def media(campo, padrao=0):
            return statistics.mean(r.get(campo, padrao) for r in ensaios) if ensaios else None
        linhas.append({
            'campanha': chave[0], 'ambiente': chave[1], 'algoritmo': chave[2], 'cenario': chave[3], 'nivel': chave[4],
            'perfil_sha256': hashlib.sha256(json.dumps(campanhas[Path(chave[0])]['perfil'], sort_keys=True).encode()).hexdigest(),
            'repeticoes': len(ensaios), 'amostras': len(amostras), 'tentativas': tentativas[chave],
            'timeouts': contagem_timeouts[chave], 'falhas': contagem_falhas[chave],
            'media_ms': statistics.mean(amostras) if amostras else None,
            **{f'p{q}_ms': percentil(amostras, q/100) if amostras else None for q in (50, 95, 99)},
            'desvio_medianas_ms': statistics.stdev(medianas) if len(medianas) > 1 else None,
            'media_medianas_ms': statistics.mean(medianas) if medianas else None,
            'media_envios': media('envios'), 'media_bytes_json': media('bytes_json'),
            'media_falsas_por_no_minuto': media('falsas_por_no_minuto'),
            'media_confirmacao_crash_ms': media('confirmacao_crash_ms'),
        })
    (saida/'summary.json').write_text(json.dumps({'linhas': linhas, 'invalidos': invalidos,
        'campanhas': list(campanhas.values()), 'timeouts': timeouts, 'falhas': falhas,
        'nota_timeouts': 'Quantis condicionados às execuções completas; vetores parciais preservados nos dados brutos e excluídos. Células sem execuções completas têm estatísticas nulas, não zero.',
        'convencao_percentil': 'interpolação linear em (n-1)*p',
        'variabilidade': 'desvio-padrão amostral das medianas por execução'}, ensure_ascii=False, indent=2))
    if linhas:
        with (saida/'metrics.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(linhas[0])); w.writeheader(); w.writerows(linhas)
        gerar_figuras(linhas, saida)
    comparar(linhas, saida)
    return {'configuracoes': len(linhas), 'execucoes_validas': sum(x['repeticoes'] for x in linhas),
            'tentativas': sum(tentativas.values()), 'timeouts': len(timeouts), 'falhas': len(falhas),
            'invalidos': len(invalidos)}


def gerar_figuras(linhas, saida):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for algoritmo in ("lamport", "gossip", "heartbeat"):
        fig, ax = plt.subplots(figsize=(3.4, 2.6), layout="constrained")
        for campanha, ambiente in sorted({(r['campanha'], r["ambiente"]) for r in linhas}):
            for cenario in ("normal", "crash"):
                dados = sorted([r for r in linhas if r['campanha'] == campanha and r["ambiente"] == ambiente
                    and r["algoritmo"] == algoritmo and r["cenario"] == cenario and r["media_medianas_ms"] is not None], key=lambda r:r["nivel"])
                if not dados:
                    continue
                ax.errorbar([r["nivel"] for r in dados], [r["media_medianas_ms"] for r in dados],
                            yerr=[r["desvio_medianas_ms"] or 0 for r in dados], marker="o",
                            capsize=3, label=f"{cenario}" if len({r['campanha'] for r in linhas}) == 1 else f"{Path(campanha).name}: {cenario}")
        ax.set_xlabel({"lamport":"Número de nós", "gossip":"Intervalo de gossip (s)",
                       "heartbeat":"Timeout de suspeita (s)"}[algoritmo])
        ax.set_ylabel("Média das medianas por ensaio (ms)")
        ax.set_title({"lamport":"RTT de mensagem com Lamport", "gossip":"Convergência observada",
                      "heartbeat":"Heartbeat: normal=RTT; crash=detecção"}[algoritmo], fontsize=8)
        ax.set_xticks(sorted({r['nivel'] for r in linhas if r['algoritmo'] == algoritmo}))
        ax.set_ylim(bottom=0)
        ax.tick_params(labelsize=7)
        ax.xaxis.label.set_size(8); ax.yaxis.label.set_size(8)
        ax.grid(alpha=.25); ax.legend(fontsize=6)
        fig.savefig(saida/f"{algoritmo}.png", dpi=180)
        fig.savefig(saida/f"{algoritmo}.pdf")
        plt.close(fig)


def comparar(linhas, saida):
    grupos = defaultdict(list)
    for r in linhas:
        grupos[(r["algoritmo"],r["cenario"],r["nivel"],r['perfil_sha256'])].append(r)
    pares=[]
    for chave, rs in grupos.items():
        for i, a in enumerate(rs):
            for b in rs[i+1:]:
                if a['ambiente'] == b['ambiente'] or a['p50_ms'] is None or b['p50_ms'] is None:
                    continue
                pares.append({"algoritmo":chave[0],"cenario":chave[1],"nivel":chave[2],
                              "ambiente_a":a["ambiente"],"ambiente_b":b["ambiente"],
                              "campanha_a":a['campanha'],"campanha_b":b['campanha'],
                              "p50_a_ms":a["p50_ms"],"p50_b_ms":b["p50_ms"],
                              "nota":"Comparação contextual; conferir mesma matriz e metadados de hardware."})
    if pares:
        with (saida/'comparacao.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(pares[0]));w.writeheader();w.writerows(pares)
    elif (saida/'comparacao.csv').exists():
        (saida/'comparacao.csv').unlink()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',default='results/raw');p.add_argument('--output',default='results/summary')
    a=p.parse_args();r=analisar(a.input,a.output)
    print(json.dumps(r,indent=2));return 0 if not r['invalidos'] and r['execucoes_validas'] else 1


if __name__=='__main__':raise SystemExit(main())
