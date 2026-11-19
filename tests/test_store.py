import unittest

from app.store import Catalogo


class TesteCatalogo(unittest.TestCase):
    def test_aplica_e_consulta_uma_atualizacao(self):
        catalogo = Catalogo()
        self.assertTrue(catalogo.aplicar("eq-1", "livre", 1, "no-1"))
        self.assertEqual(catalogo.consultar("eq-1"), {
            "valor": "livre", "contador": 1, "origem": "no-1",
        })
        self.assertIsNone(catalogo.consultar("inexistente"))

    def test_ignora_versao_antiga(self):
        catalogo = Catalogo()
        catalogo.aplicar("eq-1", "reservado", 5, "no-1")
        self.assertFalse(catalogo.aplicar("eq-1", "livre", 2, "no-2"))
        self.assertEqual(catalogo.consultar("eq-1")["valor"], "reservado")

    def test_id_do_no_desempata_contadores_iguais(self):
        catalogo = Catalogo()
        catalogo.aplicar("eq-1", "livre", 5, "no-1")
        self.assertTrue(catalogo.aplicar("eq-1", "reservado", 5, "no-2"))
        self.assertEqual(catalogo.consultar("eq-1")["valor"], "reservado")

    def test_mesclar_o_mesmo_estado_e_idempotente(self):
        origem = Catalogo()
        origem.aplicar("eq-1", "livre", 1, "no-1")
        destino = Catalogo()
        self.assertEqual(destino.mesclar(origem.snapshot()), 1)
        self.assertEqual(destino.mesclar(origem.snapshot()), 0)
        self.assertEqual(destino.snapshot(), origem.snapshot())

    def test_ordem_de_mesclagem_nao_muda_resultado(self):
        a = Catalogo()
        b = Catalogo()
        a.aplicar("eq-1", "livre", 2, "no-1")
        b.aplicar("eq-1", "reservado", 2, "no-2")
        primeiro = Catalogo()
        segundo = Catalogo()
        primeiro.mesclar(a.snapshot())
        primeiro.mesclar(b.snapshot())
        segundo.mesclar(b.snapshot())
        segundo.mesclar(a.snapshot())
        self.assertEqual(primeiro.snapshot(), segundo.snapshot())
        self.assertEqual(primeiro.consultar("eq-1")["valor"], "reservado")

    def test_agrupamento_de_mesclagens_nao_muda_resultado(self):
        a, b, c = Catalogo(), Catalogo(), Catalogo()
        a.aplicar("eq-1", "livre", 1, "no-1")
        b.aplicar("eq-1", "reservado", 2, "no-2")
        c.aplicar("eq-2", "manutencao", 1, "no-3")
        esquerda = Catalogo()
        esquerda.mesclar(a.snapshot())
        esquerda.mesclar(b.snapshot())
        esquerda.mesclar(c.snapshot())
        grupo = Catalogo()
        grupo.mesclar(b.snapshot())
        grupo.mesclar(c.snapshot())
        direita = Catalogo()
        direita.mesclar(a.snapshot())
        direita.mesclar(grupo.snapshot())
        self.assertEqual(esquerda.snapshot(), direita.snapshot())
        self.assertEqual(esquerda.snapshot(), {
            "eq-1": {"valor": "reservado", "contador": 2, "origem": "no-2"},
            "eq-2": {"valor": "manutencao", "contador": 1, "origem": "no-3"},
        })

    def test_remocao_nao_e_desfeita_por_copia_antiga(self):
        catalogo = Catalogo()
        catalogo.aplicar("eq-1", "livre", 1, "no-1")
        antigo = catalogo.snapshot()
        catalogo.aplicar("eq-1", None, 2, "no-1")
        self.assertEqual(catalogo.mesclar(antigo), 0)
        self.assertIsNone(catalogo.consultar("eq-1")["valor"])
        self.assertIn("eq-1", catalogo.snapshot())

    def test_snapshot_nao_permite_alterar_estado_interno(self):
        catalogo = Catalogo()
        catalogo.aplicar("eq-1", "livre", 1, "no-1")
        copia = catalogo.snapshot()
        copia["eq-1"]["valor"] = "alterado"
        self.assertEqual(catalogo.consultar("eq-1")["valor"], "livre")

    def test_mesma_versao_com_valores_distintos_e_rejeitada(self):
        catalogo = Catalogo()
        catalogo.aplicar("eq-1", "livre", 1, "no-1")
        with self.assertRaises(ValueError):
            catalogo.aplicar("eq-1", "reservado", 1, "no-1")
        self.assertEqual(catalogo.consultar("eq-1")["valor"], "livre")

    def test_estado_invalido_nao_e_aplicado_parcialmente(self):
        catalogo = Catalogo()
        with self.assertRaises(ValueError):
            catalogo.mesclar({
                "eq-1": {"valor": "livre", "contador": 1, "origem": "no-1"},
                "eq-2": {"valor": "livre", "contador": -1, "origem": "no-2"},
            })
        self.assertEqual(catalogo.snapshot(), {})
