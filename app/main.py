"""Inicialização configurável de cada nó."""

import json
import os
import signal
from urllib.parse import urlsplit

from app.gossip import ReplicadorGossip
from app.heartbeat import MonitorHeartbeat
from app.node import No, criar_servidor


def main():
    nome = os.environ.get("NODE_ID", "no-local")
    destinos = json.loads(os.environ.get("PEERS", "{}"))
    if not isinstance(destinos, dict):
        raise ValueError("PEERS deve ser um objeto JSON.")
    for identificador, endereco in destinos.items():
        if not isinstance(identificador, str) or not identificador:
            raise ValueError("Identificador inválido em PEERS.")
        if not isinstance(endereco, str):
            raise ValueError(f"Endereço inválido para {identificador}.")
        url = urlsplit(endereco)
        if url.scheme != "http" or not url.hostname or url.path not in ("", "/"):
            raise ValueError(f"Endereço inválido para {identificador}.")
    if destinos and nome not in destinos:
        raise ValueError("NODE_ID precisa constar em PEERS.")

    porta = int(os.environ.get("PORT", "8000"))
    no = No(nome, destinos, os.environ.get("RUN_ID", "desenvolvimento"),
            data_dir=os.environ.get("DATA_DIR"), log_dir=os.environ.get("LOG_DIR"),
            heartbeat_timeout=float(os.environ.get("HEARTBEAT_TIMEOUT", "1.5")),
            semente=int(os.environ.get("SEED", "1")))
    gossip = ReplicadorGossip(
        no, intervalo=float(os.environ.get("GOSSIP_INTERVAL", "1")),
        semente=int(os.environ.get("SEED", "1")),
    )
    monitor = MonitorHeartbeat(no, float(os.environ.get("HEARTBEAT_INTERVAL", "0.3")))
    servidor = criar_servidor(no, porta=porta)
    ativo = os.environ.get("GOSSIP_ENABLED", "1") == "1"
    with no.lock:
        no.registrar("boot", no.relogio.evento())
    if ativo:
        gossip.iniciar()
    if os.environ.get("HEARTBEAT_ENABLED", "1") == "1":
        monitor.iniciar()
    def encerrar(sinal, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, encerrar)
    print(json.dumps({"evento": "inicio", "no": nome, "porta": porta,
                      "gossip": ativo}), flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        monitor.parar()
        gossip.parar()
        servidor.server_close()


if __name__ == "__main__":
    main()
