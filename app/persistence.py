"""Checkpoint JSON atômico para falhas de processo com disco preservado."""

import json
import os
from pathlib import Path


class Persistencia:
    def __init__(self, pasta, nome):
        self.nome = nome
        self.pasta = Path(pasta) if pasta else None
        if self.pasta:
            self.pasta.mkdir(parents=True, exist_ok=True)

    def carregar(self):
        if not self.pasta or not (self.pasta / "state.json").exists():
            return {"contador": 0, "geracao": 0, "catalogo": {}, "falhas": {}}
        try:
            estado = json.loads((self.pasta / "state.json").read_text(encoding="utf-8"))
            if estado.get("schema") != 1 or estado.get("no") != self.nome:
                raise ValueError("Identidade ou schema incompatível.")
            for campo in ("contador", "geracao"):
                if type(estado.get(campo)) is not int or estado[campo] < 0:
                    raise ValueError("Contador/geração inválido no checkpoint.")
            if not isinstance(estado.get("catalogo"), dict):
                raise ValueError("Catálogo inválido no checkpoint.")
            return estado
        except (OSError, ValueError, TypeError, AttributeError) as erro:
            raise ValueError("Checkpoint inválido; não será reiniciado em zero.") from erro

    def salvar(self, contador, geracao, catalogo, falhas):
        if not self.pasta:
            return
        estado = {"schema": 1, "no": self.nome, "contador": contador,
                  "geracao": geracao, "catalogo": catalogo, "falhas": falhas}
        temporario = self.pasta / "state.tmp"
        with temporario.open("w", encoding="utf-8") as arquivo:
            json.dump(estado, arquivo, ensure_ascii=False, sort_keys=True)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, self.pasta / "state.json")
        descritor = os.open(self.pasta, os.O_RDONLY)
        try:
            os.fsync(descritor)
        finally:
            os.close(descritor)
