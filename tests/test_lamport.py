import unittest
from concurrent.futures import ThreadPoolExecutor

from app.lamport import RelogioLamport


class TesteRelogioLamport(unittest.TestCase):
    def test_eventos_locais_incrementam_o_contador(self):
        relogio = RelogioLamport()
        self.assertEqual(relogio.evento(), 1)
        self.assertEqual(relogio.evento(), 2)

    def test_continua_a_partir_do_valor_inicial(self):
        relogio = RelogioLamport(10)
        self.assertEqual(relogio.evento(), 11)

    def test_recebimento_adianta_relogio_atrasado(self):
        relogio = RelogioLamport(3)
        self.assertEqual(relogio.receber(7), 8)

    def test_recebimento_nao_regride_relogio(self):
        relogio = RelogioLamport(10)
        self.assertEqual(relogio.receber(3), 11)

    def test_encadeamento_causal_entre_dois_relogios(self):
        primeiro = RelogioLamport()
        segundo = RelogioLamport()
        envio = primeiro.evento()
        recebimento = segundo.receber(envio)
        resposta = segundo.evento()
        retorno = primeiro.receber(resposta)
        self.assertEqual((envio, recebimento, resposta, retorno), (1, 2, 3, 4))

    def test_rejeita_valor_inicial_invalido(self):
        for valor in (-1, 1.5, "3", True):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    RelogioLamport(valor)

    def test_rejeita_marca_invalida_sem_alterar_estado(self):
        relogio = RelogioLamport(5)
        for marca in (-1, 1.5, "3", True):
            with self.subTest(marca=marca):
                with self.assertRaises(ValueError):
                    relogio.receber(marca)
        self.assertEqual(relogio.evento(), 6)

    def test_eventos_concorrentes_recebem_marcas_unicas(self):
        relogio = RelogioLamport()
        tarefas = []
        resultados = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            for _ in range(400):
                tarefas.append(executor.submit(relogio.evento))
            for tarefa in tarefas:
                resultados.append(tarefa.result())
        self.assertEqual(sorted(resultados), list(range(1, 401)))


if __name__ == "__main__":
    unittest.main()
