import unittest
from threading import Event
from app.heartbeat import DetectorHeartbeat, MonitorHeartbeat


class TesteMonitor(unittest.TestCase):
    def test_par_lento_nao_bloqueia_pulsos_para_outro(self):
        bloqueado = Event()
        liberar = Event()
        recebido = Event()

        class No:
            nome = 'eu'
            destinos = {'eu': '', 'a-lento': '', 'b-saudavel': ''}

            def pulsar(self, destino):
                if destino == 'a-lento':
                    bloqueado.set()
                    liberar.wait(2)
                else:
                    recebido.set()

            def verificar_falhas(self):
                pass

            def falha_protocolo(self, *args):
                pass

        monitor = MonitorHeartbeat(No(), intervalo=.01)
        monitor.iniciar()
        try:
            self.assertTrue(bloqueado.wait(1))
            self.assertTrue(recebido.wait(.2), 'Par saudável ficou aguardando o par lento')
        finally:
            liberar.set()
            monitor.parar()


class TesteDetector(unittest.TestCase):
    def test_suspeita_apos_timeout_e_restaura_com_pulso_novo(self):
        d = DetectorHeartbeat(["no-2"], timeout=2, agora=0)
        self.assertEqual(d.verificar(agora=1), [])
        self.assertEqual(d.verificar(agora=2.1), ["no-2"])
        self.assertEqual(d.verificar(agora=3), [])
        self.assertTrue(d.observar("no-2", 1, 1, agora=3.1))
        self.assertEqual(d.suspeitos(), [])

    def test_duplicata_nao_renova_atividade(self):
        d = DetectorHeartbeat(["no-2"], timeout=2, agora=0)
        d.observar("no-2", 1, 10, agora=1)
        d.observar("no-2", 1, 10, agora=2.9)
        self.assertEqual(d.verificar(agora=3.1), ["no-2"])

    def test_geracao_antiga_nao_restaura_suspeita(self):
        d = DetectorHeartbeat(["no-2"], timeout=2, agora=0)
        d.observar("no-2", 2, 1, agora=1)
        d.verificar(agora=4)
        self.assertFalse(d.observar("no-2", 1, 999, agora=4.1))
        self.assertEqual(d.suspeitos(), ["no-2"])
        self.assertTrue(d.observar("no-2", 3, 1, agora=4.2))

    def test_timeout_invalido(self):
        for valor in (0, -1, float("nan"), True):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                DetectorHeartbeat([], timeout=valor)
