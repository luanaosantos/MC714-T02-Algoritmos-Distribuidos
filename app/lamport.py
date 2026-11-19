"""Relógio lógico de Lamport compartilhado pelas threads de um nó."""

from threading import Lock


class RelogioLamport:
    def __init__(self, valor_inicial: int = 0):
        if type(valor_inicial) is not int or valor_inicial < 0:
            raise ValueError("O contador inicial deve ser um inteiro não negativo.")

        self._contador = valor_inicial
        self._lock = Lock()

    def evento(self) -> int:
        """Registra um evento local ou envio e retorna sua marca lógica."""
        with self._lock:
            self._contador += 1
            return self._contador

    def receber(self, marca_remota: int) -> int:
        """Registra um recebimento e retorna sua marca lógica."""
        if type(marca_remota) is not int or marca_remota < 0:
            raise ValueError("A marca remota deve ser um inteiro não negativo.")

        with self._lock:
            self._contador = max(self._contador, marca_remota) + 1
            return self._contador
