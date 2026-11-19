"""Falhas no envio de requisições dos protocolos; controle fica acessível."""

import math
import random
from threading import Lock


class InjetorFalhas:
    def __init__(self, semente=1):
        self._lock = Lock()
        self._rng = random.Random(semente)
        self._regras = {}
        self.configurar({})

    def configurar(self, dados):
        if not isinstance(dados, dict):
            raise ValueError("Regras devem ser objeto JSON.")
        permitidos = {"bloqueados", "atraso_ms", "perda", "duplicacao", "tipos"}
        if set(dados) - permitidos:
            raise ValueError("Campo desconhecido nas regras de falha.")
        regras = {"bloqueados": dados.get("bloqueados", []),
                  "atraso_ms": dados.get("atraso_ms", 0),
                  "perda": dados.get("perda", 0),
                  "duplicacao": dados.get("duplicacao", 0),
                  "tipos": dados.get("tipos", ["texto", "gossip", "heartbeat"])}
        for campo in ("bloqueados", "tipos"):
            if (not isinstance(regras[campo], list)
                    or any(not isinstance(x, str) for x in regras[campo])):
                raise ValueError(f"{campo} deve ser lista de textos.")
            regras[campo] = list(regras[campo])
        if set(regras["tipos"]) - {"texto", "gossip", "heartbeat"}:
            raise ValueError("Tipo de protocolo desconhecido.")
        for campo, limite in (("atraso_ms", 2000), ("perda", 1), ("duplicacao", 1)):
            valor = regras[campo]
            if (isinstance(valor, bool) or not isinstance(valor, (int, float))
                    or not math.isfinite(valor) or not 0 <= valor <= limite):
                raise ValueError(f"{campo} fora do intervalo [0, {limite}].")
        with self._lock:
            self._regras = regras

    def estado(self):
        with self._lock:
            return {**self._regras, "bloqueados": list(self._regras["bloqueados"]),
                    "tipos": list(self._regras["tipos"])}

    def planejar(self, destino, tipo):
        with self._lock:
            r = self._regras
            if tipo not in r["tipos"]:
                return {"descartar": False, "atraso": 0, "duplicar": False}
            return {"descartar": destino in r["bloqueados"] or self._rng.random() < r["perda"],
                    "atraso": r["atraso_ms"] / 1000,
                    "duplicar": self._rng.random() < r["duplicacao"]}
