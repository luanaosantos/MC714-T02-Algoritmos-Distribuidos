"""Suspeitas locais por silêncio; geração e sequência rejeitam pulsos antigos."""

import math
import time
from threading import Event, Lock, Thread


def positivo(valor, nome):
    if (isinstance(valor, bool) or not isinstance(valor, (int, float))
            or not math.isfinite(valor) or valor <= 0):
        raise ValueError(f"{nome} deve ser finito e positivo.")


class DetectorHeartbeat:
    def __init__(self, pares, timeout=1.5, agora=None):
        positivo(timeout, "Timeout")
        self.timeout = timeout
        self._lock = Lock()
        instante = time.monotonic() if agora is None else agora
        self._pares = {}
        for nome in pares:
            self._pares[nome] = {"ultimo": instante, "geracao": -1,
                                 "pulso": -1, "suspeito": False}

    def observar(self, origem, geracao, pulso, agora=None):
        if type(geracao) is not int or geracao < 1 or type(pulso) is not int or pulso < 0:
            raise ValueError("Geração/pulso inválido.")
        instante = time.monotonic() if agora is None else agora
        with self._lock:
            if origem not in self._pares:
                return False
            p = self._pares[origem]
            if (geracao, pulso) <= (p["geracao"], p["pulso"]):
                return False
            restaurou = p["suspeito"]
            p.update(ultimo=instante, geracao=geracao, pulso=pulso, suspeito=False)
            return restaurou

    def verificar(self, agora=None):
        instante = time.monotonic() if agora is None else agora
        novos = []
        with self._lock:
            for nome, p in self._pares.items():
                if not p["suspeito"] and instante - p["ultimo"] > self.timeout:
                    p["suspeito"] = True
                    novos.append(nome)
        return sorted(novos)

    def suspeitos(self):
        with self._lock:
            return sorted(nome for nome, p in self._pares.items() if p["suspeito"])


class MonitorHeartbeat:
    def __init__(self, no, intervalo=0.3):
        positivo(intervalo, "Intervalo")
        self.no = no
        self.intervalo = intervalo
        self._parar = Event()
        self._threads = []

    def _enviar(self, nome):
        while not self._parar.wait(self.intervalo):
            try:
                self.no.pulsar(nome)
            except (ConnectionError, ValueError) as erro:
                self.no.falha_protocolo("heartbeat", nome, erro)

    def _verificar(self):
        while not self._parar.wait(min(self.intervalo / 2, 0.1)):
            self.no.verificar_falhas()

    def iniciar(self):
        if any(t.is_alive() for t in self._threads):
            return
        self._parar.clear()
        self._threads = []
        tarefas = [(self._enviar, (nome,)) for nome in sorted(self.no.destinos)
                   if nome != self.no.nome]
        tarefas.append((self._verificar, ()))
        for alvo, argumentos in tarefas:
            thread = Thread(target=alvo, args=argumentos, daemon=True)
            thread.start()
            self._threads.append(thread)

    def parar(self):
        self._parar.set()
        for thread in self._threads:
            thread.join(timeout=5)
