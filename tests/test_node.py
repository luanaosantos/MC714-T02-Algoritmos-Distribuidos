import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.node import No, criar_servidor


def requisitar(url, dados=None):
    corpo = None if dados is None else json.dumps(dados).encode()
    pedido = Request(url, data=corpo, headers={"Content-Type": "application/json"})
    with urlopen(pedido, timeout=3) as resposta:
        return json.load(resposta)


class TesteComunicacao(unittest.TestCase):
    def setUp(self):
        self.nos = {}
        self.urls = {}
        for nome in ("no-1", "no-2"):
            no = No(nome, {})
            servidor = criar_servidor(no, "127.0.0.1", 0)
            self.nos[nome] = no
            self.urls[nome] = f"http://127.0.0.1:{servidor.server_port}"
            threading.Thread(target=servidor.serve_forever, daemon=True).start()
            self.addCleanup(self.fechar_servidor, servidor)
        for no in self.nos.values():
            no.destinos.update(self.urls)

    @staticmethod
    def fechar_servidor(servidor):
        servidor.shutdown()
        servidor.server_close()

    def test_evento_local_por_http(self):
        resposta = requisitar(self.urls["no-1"] + "/event", {})
        self.assertEqual(resposta["marca"], 1)

    def test_envio_e_confirmacao_respeitam_causalidade(self):
        resposta = requisitar(self.urls["no-1"] + "/send", {
            "destino": "no-2", "conteudo": "teste",
        })
        self.assertEqual(resposta["mensagem"]["marca"], 1)
        self.assertEqual(resposta["confirmacao"]["marca_recebimento"], 2)
        self.assertEqual(resposta["confirmacao"]["marca_confirmacao"], 3)
        self.assertEqual(resposta["marca_retorno"], 4)
        estado = requisitar(self.urls["no-2"] + "/state")
        self.assertEqual(estado["recebidas"], 1)
        self.assertEqual(estado["marca"], 3)

    def test_destino_desconhecido_retorna_erro(self):
        with self.assertRaises(HTTPError) as erro:
            requisitar(self.urls["no-1"] + "/send", {
                "destino": "no-inexistente", "conteudo": "teste",
            })
        self.assertEqual(erro.exception.code, 400)

    def test_mensagem_invalida_nao_altera_relogio(self):
        with self.assertRaises(HTTPError) as erro:
            requisitar(self.urls["no-2"] + "/message", {
                "id": "m1", "origem": "no-1", "destino": "no-2",
                "marca": -1, "conteudo": "teste",
            })
        self.assertEqual(erro.exception.code, 400)
        estado = requisitar(self.urls["no-2"] + "/state")
        self.assertEqual(estado["marca"], 0)
        self.assertEqual(estado["recebidas"], 0)
