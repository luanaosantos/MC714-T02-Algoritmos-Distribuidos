import json
import tempfile
import unittest
from pathlib import Path
from scripts.analyze import verificar_matriz, percentil


class TesteAnalise(unittest.TestCase):
    def test_campanha_com_53_de_54_resultados_aponta_ausente(self):
        with tempfile.TemporaryDirectory() as pasta:
            p=Path(pasta)
            perfil={'repetitions':3,'levels':{'lamport':[3,5,7],'gossip':[.05,.1,.2],'heartbeat':[.15,.3,.6]}}
            (p/'campaign.json').write_text(json.dumps({'perfil':perfil}))
            nomes=[]
            for algoritmo,niveis in perfil['levels'].items():
                for nivel in niveis:
                    for cenario in ['normal','crash']:
                        for r in range(3):nomes.append(f'{algoritmo}-{nivel}-{cenario}-r{r}')
            for nome in nomes[:-1]:
                (p/nome).mkdir();(p/nome/'trial.json').write_text('{}')
            ausentes=verificar_matriz(p)
            self.assertEqual(len(ausentes),1)
            self.assertIn(nomes[-1],ausentes[0]['ausente'])

    def test_percentil_interpolado(self):
        self.assertEqual(percentil([1,2,3,4],.5),2.5)
        self.assertAlmostEqual(percentil([1,2,3,4],.95),3.85)

