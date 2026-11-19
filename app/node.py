"""Nó HTTP: Lamport, catálogo e antientropia push-pull."""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from app.lamport import RelogioLamport
from app.store import Catalogo, validar_registro
from app.transport import MAX_BYTES, post_json
from app.persistence import Persistencia
from app.faults import InjetorFalhas
from app.heartbeat import DetectorHeartbeat


class No:
    def __init__(self, nome: str, destinos: dict, run_id="desenvolvimento",
                 data_dir=None, log_dir=None, heartbeat_timeout=1.5, semente=1):
        self.nome = nome
        self.destinos = dict(destinos)
        self.run_id = run_id
        self.lock = Lock()
        self.persistencia = Persistencia(data_dir, nome)
        estado = self.persistencia.carregar()
        self.catalogo = Catalogo()
        self.catalogo.mesclar(estado["catalogo"])
        for registro in estado["catalogo"].values():
            if registro["contador"] > estado["contador"]:
                raise ValueError("Checkpoint com versão superior ao relógio.")
        self.relogio = RelogioLamport(estado["contador"])
        self.geracao = estado["geracao"] + 1
        self.marca = estado["contador"]
        self.sequencia = 0
        self.recebidas = 0
        self.falhas = InjetorFalhas(f"{semente}:{nome}")
        self.falhas.configurar(estado.get("falhas", {}))
        self.detector = DetectorHeartbeat(
            [p for p in destinos if p != nome], timeout=heartbeat_timeout)
        self.log_path = Path(log_dir) / "events.jsonl" if log_dir else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._salvar()

    def _salvar(self):
        self.persistencia.salvar(self.marca, self.geracao,
                                 self.catalogo.snapshot(), self.falhas.estado())

    def registrar(self, evento, marca, **campos):
        # Todas as chamadas devem ocorrer sob o lock do nó.
        self.marca = marca
        self.sequencia += 1
        registro = {
            "run_id": self.run_id, "no": self.nome, "geracao": self.geracao,
            "wall_time": datetime.now(timezone.utc).isoformat(),
            "sequencia": self.sequencia, "evento": evento,
            "marca": marca, "tempo_ns": time.monotonic_ns(), **campos,
        }
        self._salvar()  # Durabilidade antes de expor ou transmitir a marca.
        linha = json.dumps(registro, ensure_ascii=False)
        if self.log_path:
            with self.log_path.open("a", encoding="utf-8") as arquivo:
                arquivo.write(linha + "\n")
        print(linha, flush=True)

    def estado(self):
        with self.lock:
            return {"no": self.nome, "marca": self.marca,
                    "recebidas": self.recebidas,
                    "chaves": len(self.catalogo.snapshot()),
                    "geracao": self.geracao, "suspeitos": self.detector.suspeitos(),
                    "falhas": self.falhas.estado()}

    def evento_local(self, rotulo=None):
        with self.lock:
            marca = self.relogio.evento()
            self.registrar("local", marca, rotulo=rotulo)
            return {"no": self.nome, "marca": marca}

    def escrever(self, chave, valor):
        # Validar antes de consumir uma marca do relógio.
        validar_registro(chave, {"valor": valor, "contador": 0, "origem": self.nome})
        with self.lock:
            marca = self.relogio.evento()
            mudou = self.catalogo.aplicar(chave, valor, marca, self.nome)
            if not mudou:
                raise ValueError("Escrita não avançou a versão do registro.")
            self.registrar("escrita", marca, chave=chave, removido=valor is None)
            return {"no": self.nome, "chave": chave,
                    "registro": self.catalogo.consultar(chave)}

    def validar_estado(self, estado, marca_envelope):
        if not isinstance(estado, dict):
            raise ValueError("Estado deve ser um objeto JSON.")
        for chave, registro in estado.items():
            validar_registro(chave, registro)
            if registro["origem"] not in self.destinos:
                raise ValueError("Registro com origem desconhecida.")
            if registro["contador"] > marca_envelope:
                raise ValueError("Versão do registro excede a marca do envelope.")

    def receber(self, mensagem):
        origem = mensagem.get("origem")
        marca = mensagem.get("marca")
        tipo = mensagem.get("tipo", "texto")
        if not isinstance(origem, str) or origem not in self.destinos:
            raise ValueError("Origem desconhecida.")
        if mensagem.get("destino") != self.nome:
            raise ValueError("Mensagem destinada a outro nó.")
        if not isinstance(mensagem.get("id"), str) or not mensagem["id"]:
            raise ValueError("Mensagem sem identificador.")
        if type(marca) is not int or marca < 0:
            raise ValueError("Marca lógica inválida.")
        if tipo == "texto":
            if not isinstance(mensagem.get("conteudo"), str):
                raise ValueError("Conteúdo deve ser texto.")
        elif tipo == "gossip":
            self.validar_estado(mensagem.get("estado"), marca)
        elif tipo == "heartbeat":
            geracao = mensagem.get("geracao")
            if type(geracao) is not int or geracao < 1:
                raise ValueError("Heartbeat sem geração válida.")
        else:
            raise ValueError("Tipo de mensagem desconhecido.")

        with self.lock:
            recebimento = self.relogio.receber(marca)
            alteracoes = 0
            if tipo == "gossip":
                alteracoes = self.catalogo.mesclar(mensagem["estado"])
            restaurou = False
            if tipo == "heartbeat":
                restaurou = self.detector.observar(origem, mensagem["geracao"], marca)
            self.recebidas += 1
            self.registrar("recebimento", recebimento, tipo=tipo,
                           id=mensagem["id"], origem=origem,
                           geracao_origem=mensagem.get("geracao", 1),
                           marca_remota=marca, alteracoes=alteracoes)
            if restaurou:
                self.registrar("restaurado", self.relogio.evento(), alvo=origem)
            confirmacao = self.relogio.evento()
            self.registrar("envio_confirmacao", confirmacao,
                           tipo=tipo, id=mensagem["id"])
            resposta = {
                "id": mensagem["id"], "no": self.nome, "geracao": self.geracao,
                "marca_recebimento": recebimento,
                "marca_confirmacao": confirmacao,
                "alteracoes": alteracoes,
            }
            if tipo == "gossip":
                resposta["estado"] = self.catalogo.snapshot()
            return resposta

    def enviar(self, destino, conteudo):
        if not isinstance(conteudo, str) or len(conteudo) > 4096:
            raise ValueError("Conteúdo deve ser texto com até 4096 caracteres.")
        return self._trocar(destino, "texto", conteudo)

    def sincronizar(self, destino):
        return self._trocar(destino, "gossip")

    def _trocar(self, destino, tipo, conteudo=None):
        if not isinstance(destino, str) or destino not in self.destinos:
            raise ValueError("Destino desconhecido.")
        if destino == self.nome:
            raise ValueError("Escolha outro nó como destino.")
        with self.lock:
            mensagem = {
                "id": str(uuid.uuid4()), "origem": self.nome,
                "destino": destino, "tipo": tipo, "geracao": self.geracao,
                "marca": self.relogio.evento(),
            }
            if tipo == "texto":
                mensagem["conteudo"] = conteudo
            elif tipo == "gossip":
                mensagem["estado"] = self.catalogo.snapshot()
            self.registrar("envio", mensagem["marca"], tipo=tipo,
                           id=mensagem["id"], destino=destino,
                           bytes=len(json.dumps(mensagem, ensure_ascii=False).encode("utf-8")))

        # A injeção afeta pedidos dos protocolos; a API de controle fica acessível.
        plano = self.falhas.planejar(destino, tipo)
        if plano["atraso"]:
            time.sleep(plano["atraso"])
        if plano["descartar"]:
            raise ConnectionError("Mensagem descartada pela regra de falha.")
        copias = 2 if plano["duplicar"] else 1
        for copia in range(copias):
            try:
                confirmacao = post_json(self.destinos[destino] + "/message", mensagem)
                marca = confirmacao.get("marca_confirmacao")
                recebimento = confirmacao.get("marca_recebimento")
                if (confirmacao.get("id") != mensagem["id"]
                        or confirmacao.get("no") != destino
                        or type(marca) is not int
                        or type(recebimento) is not int
                        or not mensagem["marca"] < recebimento < marca):
                    raise ValueError("Confirmação incompatível com a mensagem.")
                if tipo == "gossip":
                    self.validar_estado(confirmacao.get("estado"), marca)
            except (OSError, ValueError) as erro:
                raise ConnectionError(
                    "Envio sem confirmação válida; a mensagem pode ter sido recebida."
                ) from erro
            with self.lock:
                retorno = self.relogio.receber(marca)
                alteracoes = 0
                if tipo == "gossip":
                    alteracoes = self.catalogo.mesclar(confirmacao["estado"])
                self.registrar("confirmacao_recebida", retorno, tipo=tipo,
                               id=mensagem["id"], marca_remota=marca,
                               alteracoes=alteracoes, copia=copia + 1, destino=destino,
                               geracao_remota=confirmacao.get("geracao", 1))
        return {"mensagem": mensagem, "confirmacao": confirmacao,
                "marca_retorno": retorno, "alteracoes_locais": alteracoes}

    def pulsar(self, destino):
        return self._trocar(destino, "heartbeat")

    def verificar_falhas(self):
        # Transição e log são atômicos em relação à recepção de heartbeats.
        with self.lock:
            for alvo in self.detector.verificar():
                self.registrar("suspeito", self.relogio.evento(), alvo=alvo)

    def configurar_falhas(self, dados):
        bloqueados = dados.get("bloqueados", []) if isinstance(dados, dict) else []
        if isinstance(bloqueados, list) and any(p not in self.destinos for p in bloqueados):
            raise ValueError("Nó desconhecido na lista de bloqueio.")
        self.falhas.configurar(dados)
        with self.lock:
            self.registrar("falhas_configuradas", self.relogio.evento(), regras=self.falhas.estado())
        return self.falhas.estado()

    def falha_protocolo(self, tipo, destino, erro):
        with self.lock:
            self.registrar(tipo + "_falha", self.relogio.evento(), destino=destino, erro=str(erro))

    def falha_gossip(self, destino, erro):
        with self.lock:
            marca = self.relogio.evento()
            self.registrar("gossip_falha", marca, destino=destino, erro=str(erro))


def criar_servidor(no, host="0.0.0.0", porta=8000):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def responder(self, codigo, dados):
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/health":
                self.responder(200, {"no": no.nome, "status": "ok"})
            elif url.path == "/state":
                self.responder(200, no.estado())
            elif url.path == "/catalog":
                self.responder(200, no.catalogo.snapshot())
            elif url.path == "/get":
                chave = parse_qs(url.query).get("chave", [""])[0]
                registro = no.catalogo.consultar(chave)
                if registro is None or registro["valor"] is None:
                    self.responder(404, {"erro": "Chave ausente ou removida."})
                else:
                    self.responder(200, {"chave": chave, "registro": registro})
            else:
                self.responder(404, {"erro": "Rota inexistente."})

        def do_POST(self):
            try:
                tamanho = int(self.headers.get("Content-Length", "0"))
                if tamanho <= 0 or tamanho > MAX_BYTES:
                    raise ValueError("Corpo ausente ou maior que 1 MiB.")
                dados = json.loads(self.rfile.read(tamanho))
                if not isinstance(dados, dict):
                    raise ValueError("O corpo JSON deve ser um objeto.")
                if self.path == "/event":
                    resultado = no.evento_local(dados.get("rotulo"))
                elif self.path == "/message":
                    resultado = no.receber(dados)
                elif self.path == "/send":
                    resultado = no.enviar(dados.get("destino"), dados.get("conteudo"))
                elif self.path == "/put":
                    if "valor" not in dados:
                        raise ValueError("Campo valor obrigatório; null representa remoção.")
                    resultado = no.escrever(dados.get("chave"), dados["valor"])
                elif self.path == "/sync-heartbeat":
                    resultado = no.pulsar(dados.get("destino"))
                elif self.path == "/faults":
                    resultado = no.configurar_falhas(dados)
                elif self.path == "/sync":
                    resultado = no.sincronizar(dados.get("destino"))
                else:
                    self.responder(404, {"erro": "Rota inexistente."})
                    return
            except (ValueError, UnicodeError) as erro:
                self.responder(400, {"erro": str(erro)})
                return
            except ConnectionError as erro:
                self.responder(502, {"erro": str(erro)})
                return
            except TimeoutError:
                self.responder(408, {"erro": "Tempo de leitura esgotado."})
                return
            self.responder(200, resultado)

        def log_message(self, formato, *argumentos):
            pass

    return ThreadingHTTPServer((host, porta), Handler)
