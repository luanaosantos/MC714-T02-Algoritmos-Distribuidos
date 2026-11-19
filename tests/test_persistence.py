import json
import tempfile
import unittest
from pathlib import Path
from app.node import No


class TestePersistencia(unittest.TestCase):
    def test_reinicio_preserva_catalogo_e_avanca_contador(self):
        with tempfile.TemporaryDirectory() as pasta:
            primeiro = No("no-1", {"no-1": "http://localhost:1"}, data_dir=pasta)
            registro = primeiro.escrever("eq", "livre")["registro"]
            segundo = No("no-1", {"no-1": "http://localhost:1"}, data_dir=pasta)
            self.assertEqual(segundo.catalogo.consultar("eq"), registro)
            novo = segundo.escrever("eq", "reservado")["registro"]
            self.assertGreater(novo["contador"], registro["contador"])
            self.assertGreater(segundo.geracao, primeiro.geracao)

    def test_arquivo_corrompido_nao_reinicia_em_zero(self):
        with tempfile.TemporaryDirectory() as pasta:
            Path(pasta, "state.json").write_text("incompleto")
            with self.assertRaises(ValueError):
                No("no-1", {}, data_dir=pasta)

    def test_persistencia_nao_mistura_identidades(self):
        with tempfile.TemporaryDirectory() as pasta:
            No("no-1", {}, data_dir=pasta)
            with self.assertRaises(ValueError):
                No("no-2", {}, data_dir=pasta)
