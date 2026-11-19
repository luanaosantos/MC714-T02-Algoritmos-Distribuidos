"""Antientropia periódica: um par aleatório por rodada, troca push-pull."""

import math
import random
from threading import Event, Thread


class ReplicadorGossip:
    def __init__(self, no, intervalo=1.0, semente=1):
        if (isinstance(intervalo, bool)
                or not isinstance(intervalo, (int, float))
                or not math.isfinite(intervalo) or intervalo <= 0):
            raise ValueError("Intervalo do gossip deve ser finito e positivo.")
        self.no = no
        self.intervalo = intervalo
        self.aleatorio = random.Random(f"{semente}:{no.nome}")
        self._parar = Event()
        self._thread = None

    def rodada(self):
        destinos = sorted(self.no.destinos)
        if self.no.nome in destinos:
            destinos.remove(self.no.nome)
        if not destinos:
            return None
        destino = self.aleatorio.choice(destinos)
        try:
            return self.no.sincronizar(destino)
        except (ConnectionError, ValueError) as erro:
            self.no.falha_gossip(destino, erro)
            return None

    def _executar(self):
        while not self._parar.wait(self.intervalo):
            self.rodada()

    def iniciar(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._parar.clear()
        self._thread = Thread(target=self._executar, daemon=True, name="gossip")
        self._thread.start()

    def parar(self):
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
