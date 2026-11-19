import threading
import time
import unittest
from urllib.error import HTTPError

from app.node import No, criar_servidor
from test_node import requisitar


class TesteCatalogoHTTP(unittest.TestCase):
    def setUp(self):
        self.nos = {}
        self.urls = {}
        for nome in ("no-1", "no-2", "no-3"):
            no = No(nome, {})
            servidor = criar_servidor(no, "127.0.0.1", 0)
            self.nos[nome] = no
            self.urls[nome] = f"http://127.0.0.1:{servidor.server_port}"
            threading.Thread(target=servidor.serve_forever, daemon=True).start()
            self.addCleanup(self.fechar, servidor)
        for no in self.nos.values():
            no.destinos.update(self.urls)

    @staticmethod
    def fechar(servidor):
        servidor.shutdown()
        servidor.server_close()

    def chamar(self, nome, rota, dados=None):
        return requisitar(self.urls[nome] + rota, dados)

    def test_escrita_local_usa_marca_do_no(self):
        resposta = self.chamar("no-1", "/put", {"chave": "eq-1", "valor": "livre"})
        self.assertEqual(resposta["registro"], {
            "valor": "livre", "contador": 1, "origem": "no-1",
        })
        self.assertEqual(self.chamar("no-2", "/catalog"), {})

    def test_sincronizacao_push_pull_troca_dados_nos_dois_sentidos(self):
        self.chamar("no-1", "/put", {"chave": "a", "valor": "A"})
        self.chamar("no-2", "/put", {"chave": "b", "valor": "B"})
        self.chamar("no-1", "/sync", {"destino": "no-2"})
        esperado = {
            "a": {"valor": "A", "contador": 1, "origem": "no-1"},
            "b": {"valor": "B", "contador": 1, "origem": "no-2"},
        }
        self.assertEqual(self.chamar("no-1", "/catalog"), esperado)
        self.assertEqual(self.chamar("no-2", "/catalog"), esperado)

    def test_conflito_converge_sem_reversionar_dados(self):
        self.chamar("no-1", "/put", {"chave": "eq-1", "valor": "livre"})
        self.chamar("no-2", "/put", {"chave": "eq-1", "valor": "reservado"})
        self.chamar("no-1", "/sync", {"destino": "no-2"})
        self.chamar("no-2", "/sync", {"destino": "no-3"})
        esperado = {"eq-1": {"valor": "reservado", "contador": 1, "origem": "no-2"}}
        for nome in self.urls:
            self.assertEqual(self.chamar(nome, "/catalog"), esperado)
        escrita = self.chamar("no-3", "/put", {"chave": "eq-1", "valor": "manutencao"})
        self.assertGreater(escrita["registro"]["contador"], 1)

    def test_remocao_e_replicada_com_tombstone(self):
        self.chamar("no-1", "/put", {"chave": "eq-1", "valor": "livre"})
        self.chamar("no-1", "/sync", {"destino": "no-2"})
        self.chamar("no-1", "/put", {"chave": "eq-1", "valor": None})
        self.chamar("no-2", "/sync", {"destino": "no-1"})
        self.assertIsNone(self.chamar("no-2", "/catalog")["eq-1"]["valor"])
        with self.assertRaises(HTTPError) as erro:
            self.chamar("no-2", "/get?chave=eq-1")
        self.assertEqual(erro.exception.code, 404)

    def test_escrita_invalida_nao_incrementa_relogio(self):
        with self.assertRaises(HTTPError) as erro:
            self.chamar("no-1", "/put", {"chave": "", "valor": "teste"})
        self.assertEqual(erro.exception.code, 400)
        self.assertEqual(self.chamar("no-1", "/state")["marca"], 0)

    def test_snapshot_mais_adiantado_que_envelope_e_rejeitado(self):
        with self.assertRaises(HTTPError) as erro:
            self.chamar("no-2", "/message", {
                "id": "g1", "tipo": "gossip", "origem": "no-1",
                "destino": "no-2", "marca": 1,
                "estado": {"eq-1": {"valor": "livre", "contador": 99, "origem": "no-1"}},
            })
        self.assertEqual(erro.exception.code, 400)
        self.assertEqual(self.chamar("no-2", "/catalog"), {})

    def test_gossip_periodico_propaga_sem_comando_manual(self):
        # Importação local permite verificar antes as novas rotas HTTP.
        from app.gossip import ReplicadorGossip
        replicador = ReplicadorGossip(self.nos["no-1"], intervalo=0.02, semente=7)
        self.addCleanup(replicador.parar)
        self.chamar("no-2", "/put", {"chave": "eq-1", "valor": "livre"})
        replicador.iniciar()
        limite = time.monotonic() + 3
        while time.monotonic() < limite:
            catalogo = self.chamar("no-1", "/catalog")
            if "eq-1" in catalogo:
                break
            time.sleep(0.02)
        self.assertEqual(catalogo["eq-1"]["valor"], "livre")

    def test_intervalo_invalido_e_rejeitado(self):
        from app.gossip import ReplicadorGossip
        for intervalo in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(intervalo=intervalo):
                with self.assertRaises(ValueError):
                    ReplicadorGossip(self.nos["no-1"], intervalo=intervalo)
