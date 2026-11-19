"""Controlador de processos ou Compose; não participa dos protocolos."""

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


def hardware():
    """Recursos visíveis ao controlador (Docker tem seus limites separados)."""
    info = {'cpu_model': platform.processor() or platform.machine(), 'memory_bytes': None}
    try:
        for linha in Path('/proc/cpuinfo').read_text().splitlines():
            if linha.startswith('model name'):
                info['cpu_model'] = linha.split(':', 1)[1].strip()
                break
        for linha in Path('/proc/meminfo').read_text().splitlines():
            if linha.startswith('MemTotal:'):
                info['memory_bytes'] = int(linha.split()[1]) * 1024
                break
    except OSError:
        pass
    return info


def http(url, rota, dados=None, timeout=5):
    corpo = None if dados is None else json.dumps(dados).encode("utf-8")
    pedido = Request(url + rota, data=corpo, headers={"Content-Type": "application/json"})
    with build_opener(ProxyHandler({})).open(pedido, timeout=timeout) as resposta:
        return json.load(resposta)


def esperar(condicao, timeout=10, intervalo=0.03):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicao():
            return
        time.sleep(intervalo)
    raise TimeoutError("Condição não observada no prazo.")


def digest_codigo():
    h = hashlib.sha256()
    for pasta in ("app", "scripts"):
        for p in sorted((ROOT / pasta).glob("*.py")):
            h.update(str(p.relative_to(ROOT)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def finalizar_compose(pasta, nomes, comando):
    """Exportar antes de remover os volumes exclusivos deste ensaio."""
    subprocess.run(comando("stop", "--timeout", "5"), check=True,
                   stdout=subprocess.DEVNULL)
    for nome in nomes:
        container = subprocess.check_output(
            comando('ps', '--all', '--quiet', nome), text=True).strip()
        if not container:
            continue
        for origem, destino in (('/dados/.', 'data'), ('/logs/.', 'logs')):
            subprocess.run(['docker', 'cp', f'{container}:{origem}',
                            str(pasta/nome/destino)], check=True,
                           stdout=subprocess.DEVNULL)
    # Somente volumes do projeto exclusivo deste ensaio, já exportados.
    subprocess.run(comando("down", "--volumes", "--timeout", "5"), check=True,
                   stdout=subprocess.DEVNULL)


def recuperar_compose_interrompido(pasta):
    pasta = Path(pasta).resolve()
    compose = pasta / "compose.run.json"
    nomes = list(json.loads(compose.read_text())["services"])
    projeto = "mc714-" + hashlib.sha256(str(pasta).encode()).hexdigest()[:12]
    def comando(*args):
        return ["docker", "compose", "-p", projeto, "-f", str(compose), *args]
    finalizar_compose(pasta, nomes, comando)


class Cluster:
    def __init__(self, pasta, config):
        self.pasta = Path(pasta).resolve()
        self.pasta.mkdir(parents=True, exist_ok=False)
        self.config = dict(config)
        self.backend = config.get("backend", "process")
        if self.backend not in ("process", "compose"):
            raise ValueError("Backend deve ser process ou compose.")
        n = config.get("nodes", 3)
        if type(n) is not int or n < 3 or n > 32:
            raise ValueError("Use entre 3 e 32 nós.")
        self.nomes = [f"no-{i + 1}" for i in range(n)]
        self.run_id = self.pasta.name
        reservas = []
        self.urls = {}
        for nome in self.nomes:
            if self.backend == 'compose':
                self.urls[nome] = 'http://127.0.0.1:0'
                continue
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            self.urls[nome] = f"http://127.0.0.1:{s.getsockname()[1]}"
            reservas.append(s)
        for s in reservas:
            s.close()
        self.procs = {}
        self.arquivos = {}
        self.projeto = "mc714-" + hashlib.sha256(str(self.pasta).encode()).hexdigest()[:12]
        self.compose = self.pasta / "compose.run.json"
        self.iniciado = False
        self.metadata = {
            "run_id": self.run_id, "nodes": self.nomes, "config": self.config,
            "backend": self.backend, "python": sys.version, "os": platform.platform(),
            "cpu_count": os.cpu_count(), "machine": platform.machine(),
            "hardware": hardware(),
            "source_sha256": digest_codigo(), "inicio_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            self.metadata["commit"] = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            self.metadata["commit"] = None
        if self.backend == "compose":
            docker_info = json.loads(subprocess.check_output(
                ['docker', 'info', '--format', '{{json .}}'], text=True))
            self.metadata['docker_resources'] = {
                'cpus': docker_info.get('NCPU'), 'memory_bytes': docker_info.get('MemTotal'),
                'os': docker_info.get('OperatingSystem'), 'kernel': docker_info.get('KernelVersion')}
            self.metadata["docker_version"] = subprocess.check_output(
                ["docker", "version", "--format", "{{json .}}"], text=True).strip()
            self.metadata["compose_version"] = subprocess.check_output(
                ["docker", "compose", "version"], text=True).strip()
            self.metadata["image_id"] = subprocess.check_output(
                ["docker", "image", "inspect", config.get("image", "mc714-trabalho2:dev"),
                 "--format", "{{.Id}}"], text=True).strip()
        self.gravar_json("metadata.json", self.metadata)
        self.gravar_json("config.json", self.config)

    def gravar_json(self, nome, valor):
        (self.pasta / nome).write_text(json.dumps(valor, ensure_ascii=False, indent=2), encoding="utf-8")

    def registrar(self, evento, **campos):
        registro = {"evento": evento, "tempo_ns": time.monotonic_ns(), **campos}
        with (self.pasta / "controller.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        return registro["tempo_ns"]

    def ambiente(self, nome, docker=False):
        pares = self.urls
        porta = self.urls[nome].rsplit(":", 1)[1]
        if docker:
            pares = {}
            for p in self.nomes:
                pares[p] = f"http://{p}:8000"
            porta = "8000"
        c = self.config
        return {
            "NODE_ID": nome, "PORT": porta, "PEERS": json.dumps(pares),
            "RUN_ID": self.run_id, "DATA_DIR": "/dados" if docker else str(self.pasta / nome / "data"),
            "LOG_DIR": "/logs" if docker else str(self.pasta / nome / "logs"),
            "GOSSIP_INTERVAL": str(c.get("gossip_interval", 0.1)),
            "GOSSIP_ENABLED": "1" if c.get("gossip", True) else "0",
            "HEARTBEAT_INTERVAL": str(c.get("heartbeat_interval", 0.1)),
            "HEARTBEAT_TIMEOUT": str(c.get("heartbeat_timeout", 0.6)),
            "HEARTBEAT_ENABLED": "1" if c.get("heartbeat", True) else "0",
            "SEED": str(c.get("seed", 1)),
        }

    def comando_compose(self, *args):
        return ["docker", "compose", "-p", self.projeto, "-f", str(self.compose), *args]

    def _subir_processo(self, nome):
        pasta = self.pasta / nome
        pasta.mkdir(exist_ok=True)
        f = (pasta / "stdout.log").open("a", encoding="utf-8")
        self.arquivos[nome] = f
        env = os.environ.copy()
        env.update(self.ambiente(nome))
        self.procs[nome] = subprocess.Popen(
            [sys.executable, "-u", "-m", "app.main"], cwd=ROOT,
            env=env, stdout=f, stderr=subprocess.STDOUT)

    def start(self):
        self.iniciado = True
        if self.backend == "process":
            for nome in self.nomes:
                self._subir_processo(nome)
        else:
            services = {}
            volumes = {}
            for nome in self.nomes:
                for parte in ("data", "logs"):
                    (self.pasta / nome / parte).mkdir(parents=True, exist_ok=True)
                services[nome] = {
                    "image": self.config.get("image", "mc714-trabalho2:dev"),
                    "environment": self.ambiente(nome, True),
                    "ports": ['127.0.0.1::8000'],
                    "volumes": [f"{nome}-data:/dados", f"{nome}-logs:/logs"],
                }
                volumes[f'{nome}-data'] = {}
                volumes[f'{nome}-logs'] = {}
            self.metadata['docker_storage'] = 'named volumes; exported after stop'
            self.compose.write_text(json.dumps({"services": services, 'volumes': volumes}, indent=2))
            subprocess.run(self.comando_compose("up", "-d"), check=True,
                           stdout=subprocess.DEVNULL)
            for nome in self.nomes:
                endereco = subprocess.check_output(
                    self.comando_compose('port', nome, '8000'), text=True).strip()
                self.urls[nome] = 'http://' + endereco
        for nome in self.nomes:
            self.aguardar_saude(nome)
        if self.backend == 'compose':
            self.metadata['application_runtime'] = json.loads(subprocess.check_output(
                self.comando_compose('exec', '-T', self.nomes[0], 'python', '-c',
                    'import json,platform,sys; print(json.dumps({"python":sys.version,"os":platform.platform()}))'),
                text=True))
        else:
            self.metadata['application_runtime'] = {'python': sys.version, 'os': platform.platform()}
        self.metadata['controller_runtime'] = {'python': sys.version, 'os': platform.platform()}
        self.gravar_json('metadata.json', self.metadata)
        self.registrar("cluster_pronto")
        return self

    def aguardar_saude(self, nome):
        def pronto():
            try:
                return self.chamar(nome, "/health")["status"] == "ok"
            except (OSError, ValueError):
                return False
        esperar(pronto, self.config.get("startup_timeout", 20))

    def chamar(self, nome, rota, dados=None):
        return http(self.urls[nome], rota, dados)

    def matar(self, nome):
        if self.backend == "process":
            self.procs[nome].kill()
            self.procs[nome].wait(timeout=5)
            self.arquivos[nome].close()
        else:
            subprocess.run(self.comando_compose("kill", "-s", "SIGKILL", nome), check=True,
                           stdout=subprocess.DEVNULL)
        return self.registrar("crash", alvo=nome)

    def reiniciar(self, nome):
        if self.backend == "process":
            self._subir_processo(nome)
        else:
            subprocess.run(self.comando_compose("start", nome), check=True,
                           stdout=subprocess.DEVNULL)
            # Portas dinâmicas podem mudar quando o Docker inicia o contêiner.
            endereco = subprocess.check_output(
                self.comando_compose('port', nome, '8000'), text=True).strip()
            self.urls[nome] = 'http://' + endereco
        self.aguardar_saude(nome)
        return self.registrar("reinicio", alvo=nome)

    def regras(self, nome, regras):
        resultado = self.chamar(nome, "/faults", regras)
        self.registrar("regras", alvo=nome, regras=resultado)

    def particao(self):
        esquerda = self.nomes[:len(self.nomes)//2]
        direita = self.nomes[len(self.nomes)//2:]
        for nome in esquerda:
            self.regras(nome, {"bloqueados": direita})
        for nome in direita:
            self.regras(nome, {"bloqueados": esquerda})
        self.registrar("particao", grupos=[esquerda, direita])

    def curar(self):
        for nome in self.nomes:
            self.regras(nome, {})
        self.registrar("rede_restaurada")

    def convergir(self, chave, registro, nomes=None, timeout=10):
        nomes = self.nomes if nomes is None else nomes
        def igual():
            try:
                return all(self.chamar(n, "/catalog").get(chave) == registro for n in nomes)
            except (OSError, ValueError):
                return False
        esperar(igual, timeout)

    def stop(self):
        if not self.iniciado:
            return
        if self.backend == "process":
            for p in self.procs.values():
                if p.poll() is None:
                    p.terminate()
            for p in self.procs.values():
                try:
                    p.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait()
            for f in self.arquivos.values():
                f.close()
        else:
            finalizar_compose(self.pasta, self.nomes, self.comando_compose)
        self.registrar("cluster_encerrado")
        hashes = {}
        for p in sorted(self.pasta.glob("no-*/logs/events.jsonl")):
            hashes[str(p.relative_to(self.pasta))] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.metadata["log_sha256"] = hashes
        self.gravar_json("metadata.json", self.metadata)
        self.iniciado = False

    def __enter__(self):
        try:
            return self.start()
        except Exception:
            self.stop()
            raise

    def __exit__(self, *args):
        self.stop()
