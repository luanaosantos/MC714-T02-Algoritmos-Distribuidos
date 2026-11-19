# MC714 — Catálogo distribuído

Catálogo de equipamentos em Python 3.12, com relógio lógico de Lamport, replicação gossip por antientropia push-pull e detector de falhas por heartbeat. Cada nó executa em processo/contêiner próprio, comunica-se por HTTP/JSON e mantém seu volume. O catálogo oferece consistência eventual e reconciliação determinística de versões; não implementa reserva exclusiva.

Luana Oliveira dos Santos (RA 230559) e Maria Eduarda Xavier Messia (RA 183611).

- Relatório final: [relatorio.pdf](relatorio.pdf).
- Apresentação: <https://www.youtube.com/watch?v=Kv4Qzr8fzmg>.
- Repositório informado: <https://github.com/luanaosantos/MC714-T02-Algoritmos-Distribuidos>.

## Estrutura da entrega

| Caminho | Conteúdo |
|---|---|
| `app/` | Algoritmos, catálogo, HTTP, persistência e injeção de falhas |
| `tests/` | Testes de correção, concorrência, recuperação e análise |
| `compose.yaml`, `Dockerfile` | Ambiente local com três nós |
| `configs/` | Configurações de execução, matriz experimental |
| `scripts/` | Cliente, cenários, experimentos, auditoria e análise |
| `results/raw/campanha-heartbeat-20261117/` | 54 tentativas da campanha usada no relatório |
| `results/summary-heartbeat-20261117/` | Estatísticas em CSV/JSON e figuras |
| `results/raw/docker-heartbeat-validado-20261117/` | Seis cenários integrados aprovados |
| `results/raw/compose-referencia-validado-20261118/` | Validação do Compose interativo |
| `results/raw/docker-heartbeat-20261117/`, `results/raw/diagnostico-porta-20261117/` | Duas falhas iniciais de controle e diagnóstico citados no relatório |
| `relatorio.pdf` | Relatório final: modelo, propriedades, método, resultados e limitações |

`results/dev/` recebe logs do ambiente interativo e pode ser excluída do pacote de entrega. `.venv/` e caches são arquivos locais regeneráveis. `.build/` contém intermediários antigos do relatório; essas pastas podem ficar fora do pacote.

## Construir, iniciar, testar e remover o ambiente

Requisitos: Python 3.12 e Docker com Compose compatível com v2. Aplicação e testes usam apenas a biblioteca padrão de Python; não precisam instalar os requirements de análise.

```bash
python3 -m unittest discover -s tests -v
docker compose config --quiet
HEARTBEAT_TIMEOUT=3 GOSSIP_INTERVAL=0.5 docker compose up --build -d --wait
docker compose ps
python3 scripts/verificar_gossip.py
```

O verificador cria uma chave própria e confere escrita, atualização e remoção versionada nos três nós, sem sincronização manual. O modelo e as propriedades de correção estão nas seções II e III do relatório.

```bash
python3 -m scripts.client --url http://127.0.0.1:8001 put equipamento-17 disponivel
python3 -m scripts.client --url http://127.0.0.1:8002 get equipamento-17
python3 -m scripts.client --url http://127.0.0.1:8003 state
docker compose kill node3
python3 -m scripts.client --url http://127.0.0.1:8001 state
docker compose start node3
docker compose logs --no-color
docker compose down
```

Consultas imediatas podem mostrar versões antigas; repetir até observar a propagação. A suspeita aparece após silêncio suficiente desde o último heartbeat e não prova morte. Reiniciar preserva o catálogo e aumenta a geração. `docker compose down` preserva volumes; `docker compose down -v` remove também os dados persistidos. Os logs em `results/dev/` permanecem na máquina.

## Cenários automatizados

Cada comando cria projeto e volumes próprios, registra evidências e encerra seus recursos. Executar sequencialmente:

```bash
docker compose build
python3 -m scripts.run_scenario --config configs/docker.json --scenario normal
python3 -m scripts.run_scenario --config configs/docker.json --scenario crash
python3 -m scripts.run_scenario --config configs/docker.json --scenario restart
python3 -m scripts.run_scenario --config configs/docker.json --scenario partition
python3 -m scripts.run_scenario --config configs/docker.json --scenario delay_loss
python3 -m scripts.run_scenario --config configs/docker.json --scenario combined
```

Os vereditos ficam em `verdict.json` na pasta indicada pelo comando. Para auditar uma execução existente:

```bash
python3 -m scripts.check_logs results/raw/docker-heartbeat-validado-20261117/restart
```

A configuração `configs/local.json` permite desenvolvimento com processos separados e TCP real. A referência da avaliação é a execução em contêineres. Partições, perda, atraso e duplicação são injetados nos pedidos da aplicação; não controlam todos os pacotes TCP nem as respostas HTTP.

## Reproduzir os experimentos

O perfil usa três algoritmos × três níveis × normal/crash × três repetições, com sementes 101–103: 54 tentativas. Lamport varia 3/5/7 nós; gossip varia intervalo de 0,2/0,5/1 s; heartbeat varia timeout de 1,5/3/6 s. Cada tentativa usa volumes novos e aquecimento de 2 s. Evitar outra carga experimental simultânea.

```bash
docker compose build
python3 -m scripts.run_experiments --config configs/experiments-docker-54.json --runtime configs/docker.json --output results/raw/minha-campanha
```

Usar uma pasta de saída nova. Para lotes, acrescentar `--max-trials 3` e, nas chamadas seguintes, `--resume`. Fonte, perfil e runtime devem permanecer idênticos. Código de saída 3 indica lote aceito com campanha incompleta; 0 indica conclusão aceita; 1 exige examinar as falhas. Não executar duas retomadas simultâneas.

A campanha entregue contém **50 medições completas e quatro incompletas**, com auditorias positivas nas 54 tentativas. Lamport e gossip completaram as 18 tentativas de cada algoritmo. No heartbeat, houve três falhas de medição no cenário normal com timeout de 1,5 s e uma no cenário de queda com esse timeout. Essas tentativas permanecem nos dados brutos; seus vetores parciais não entram nos percentis.

`--resume --allow-timeouts` aceita somente timeout auditado de convergência gossip; não libera as quatro falhas de heartbeat desta campanha. Resultados malsucedidos não devem ser sobrescritos para substituí-los por sucesso.

## Dependências de análise e estatísticas

Há dois arquivos com funções diferentes: `requirements-dev.txt` declara a dependência direta e sua faixa de versões; `requirements-dev.lock.txt` fixa as versões do ambiente usado, incluindo dependências transitivas. Para reprodução, instalar **apenas o lock**:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock.txt
MPLCONFIGDIR=/tmp/mc714-mpl .venv/bin/python -m scripts.analyze --input results/raw/campanha-heartbeat-20261117 --output results/summary-heartbeat-20261117
```

Para uma nova campanha, substituir entrada e saída no último comando. Analisar uma campanha por vez: as outras pastas de `results/raw/` guardam cenários e diagnósticos com métricas distintas.

O resumo apresenta média, p50/p95/p99 e desvio-padrão amostral das medianas por execução. Quantis usam interpolação linear em `(n-1)*p`. As figuras mostram média das medianas e seu desvio-padrão, sem intervalo de confiança. Estatísticas usam apenas medições completas; células sem completos têm valores nulos e não aparecem como zero. A semente reproduz escolhas pseudoaleatórias, mas não determina rede ou escalonamento. As limitações e definições das métricas estão nas seções IV e V do relatório.

## Bônus

Foram implementados o terceiro algoritmo (heartbeat), cenários adicionais de recuperação/partição/falhas combinadas e integração em um catálogo de equipamentos. A avaliação experimental do heartbeat permanece parcial. Não houve execução comparativa na nuvem do IC; a configuração `configs/cloud.json` não constitui evidência de execução.
