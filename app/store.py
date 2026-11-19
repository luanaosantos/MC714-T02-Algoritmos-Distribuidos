"""Catálogo com versões lógicas e combinação determinística de estados."""

from copy import deepcopy
from threading import Lock


def validar_registro(chave, registro):
    if not isinstance(chave, str) or not chave or len(chave) > 128:
        raise ValueError("Chave deve ter entre 1 e 128 caracteres.")
    campos = {"valor", "contador", "origem"}
    if not isinstance(registro, dict) or set(registro) != campos:
        raise ValueError("Registro deve conter valor, contador e origem.")
    valor = registro["valor"]
    if valor is not None and (not isinstance(valor, str) or len(valor) > 4096):
        raise ValueError("Valor deve ser texto com até 4096 caracteres ou None.")
    contador = registro["contador"]
    if type(contador) is not int or contador < 0:
        raise ValueError("Contador deve ser inteiro não negativo.")
    origem = registro["origem"]
    if not isinstance(origem, str) or not origem or len(origem) > 64:
        raise ValueError("Origem deve ter entre 1 e 64 caracteres.")


class Catalogo:
    def __init__(self):
        self._registros = {}
        self._lock = Lock()

    def aplicar(self, chave, valor, contador, origem):
        registro = {"valor": valor, "contador": contador, "origem": origem}
        return self.mesclar({chave: registro}) == 1

    def consultar(self, chave):
        with self._lock:
            return deepcopy(self._registros.get(chave))

    def snapshot(self):
        """Retorna uma cópia independente, incluindo remoções versionadas."""
        with self._lock:
            return deepcopy(self._registros)

    def mesclar(self, estado):
        """Aplica versões maiores e retorna quantas chaves foram alteradas."""
        if not isinstance(estado, dict):
            raise ValueError("Estado deve ser um objeto com chaves e registros.")
        copia = deepcopy(estado)
        for chave, registro in copia.items():
            validar_registro(chave, registro)

        with self._lock:
            alteracoes = {}
            for chave, registro in copia.items():
                atual = self._registros.get(chave)
                versao = (registro["contador"], registro["origem"])

                if atual is None:
                    alteracoes[chave] = registro
                    continue

                versao_atual = (atual["contador"], atual["origem"])
                if versao > versao_atual:
                    alteracoes[chave] = registro
                elif versao == versao_atual and registro != atual:
                    raise ValueError("Mesma versão identifica valores diferentes.")

            # Só altera o catálogo depois de conferir todo o estado.
            self._registros.update(alteracoes)
            return len(alteracoes)
