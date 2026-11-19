import tempfile
import unittest
from app.node import No


class TesteIntegracaoExtra(unittest.TestCase):
    def test_regras_de_particao_sobrevivem_reinicio(self):
        with tempfile.TemporaryDirectory() as pasta:
            pares={"no-1":"http://localhost:1", "no-2":"http://localhost:2"}
            n=No("no-1",pares,data_dir=pasta)
            n.configurar_falhas({"bloqueados":["no-2"]})
            novo=No("no-1",pares,data_dir=pasta)
            self.assertTrue(novo.falhas.planejar("no-2","gossip")["descartar"])
            novo.configurar_falhas({})
            self.assertFalse(novo.falhas.planejar("no-2","gossip")["descartar"])

    def test_novas_escritas_apos_reinicio_superam_estado_restaurado(self):
        with tempfile.TemporaryDirectory() as pasta:
            n=No("no-1",{},data_dir=pasta)
            for _ in range(3):n.evento_local()
            antigo=n.escrever('eq','a')['registro']
            novo=No("no-1",{},data_dir=pasta)
            registro=novo.escrever('eq','b')['registro']
            self.assertEqual(registro['contador'], antigo['contador']+1)

    def test_estado_restaurado_nao_aceita_relogio_abaixo_das_versoes(self):
        import json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as pasta:
            Path(pasta,'state.json').write_text(json.dumps({
                'schema':1,'no':'no-1','contador':1,'geracao':1,
                'catalogo':{'eq':{'valor':'a','contador':2,'origem':'no-1'}},'falhas':{}}))
            with self.assertRaises(ValueError):No('no-1',{},data_dir=pasta)

    def test_registro_de_suspeita_precede_restauracao_concorrente(self):
        import json
        import threading
        from pathlib import Path
        with tempfile.TemporaryDirectory() as pasta:
            n=No('no-1',{'no-1':'http://localhost:1','no-2':'http://localhost:2'},
                 log_dir=pasta,heartbeat_timeout=.1)
            n.detector.observar('no-2',1,1,agora=0)
            calculada=threading.Event();liberar=threading.Event();recebida=threading.Event()
            original=n.detector.verificar
            def intercalar():
                resultado=original()
                calculada.set()
                liberar.wait(2)
                return resultado
            n.detector.verificar=intercalar
            t=threading.Thread(target=n.verificar_falhas);t.start()
            self.assertTrue(calculada.wait(2))
            def receber():
                n.receber({'id':'h','origem':'no-2','destino':'no-1','tipo':'heartbeat',
                           'geracao':1,'marca':5})
                recebida.set()
            r=threading.Thread(target=receber);r.start()
            recebida.wait(.2);liberar.set();t.join(2);r.join(2)
            self.assertFalse(t.is_alive());self.assertFalse(r.is_alive())
            eventos=[json.loads(l)['evento'] for l in Path(pasta,'events.jsonl').read_text().splitlines()]
            self.assertLess(eventos.index('suspeito'),eventos.index('restaurado'))
