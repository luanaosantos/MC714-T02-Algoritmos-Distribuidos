import unittest
from app.faults import InjetorFalhas


class TesteFalhas(unittest.TestCase):
    def test_bloqueio_direcional_e_reset(self):
        f = InjetorFalhas(7)
        f.configurar({"bloqueados": ["no-2"]})
        self.assertTrue(f.planejar("no-2", "gossip")["descartar"])
        self.assertFalse(f.planejar("no-3", "gossip")["descartar"])
        f.configurar({})
        self.assertFalse(f.planejar("no-2", "gossip")["descartar"])

    def test_perda_e_duplicacao_extremas(self):
        f = InjetorFalhas(7)
        f.configurar({"perda": 1})
        self.assertTrue(f.planejar("no-2", "texto")["descartar"])
        f.configurar({"duplicacao": 1})
        self.assertTrue(f.planejar("no-2", "texto")["duplicar"])

    def test_configuracao_invalida_preserva_anterior(self):
        f = InjetorFalhas(7)
        f.configurar({"perda": 1})
        with self.assertRaises(ValueError):
            f.configurar({"perda": -1})
        self.assertEqual(f.estado()["perda"], 1)
