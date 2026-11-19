"""Timeout experimental é evidência, não uma latência nem um ensaio completo."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import analyze


class TesteResultadosExperimentais(unittest.TestCase):
    def test_timeout_auditado_e_reportado_sem_usar_amostras_parciais(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            perfil = {'repetitions': 3, 'levels': {'gossip': [.2, .5, 1.]}}
            (root/'campaign.json').write_text(json.dumps({'perfil': perfil, 'runtime': {'ambiente': 'docker'}}))
            for nivel in [.2, .5, 1.]:
                for cenario in ['normal', 'crash']:
                    for rep in range(3):
                        nome = f'gossip-{nivel}-{cenario}-r{rep}'
                        p = root/nome
                        p.mkdir()
                        timeout = nivel == 1. and cenario == 'crash' and rep == 0
                        r = {'run_id': nome, 'environment': 'docker', 'algoritmo': 'gossip',
                             'nivel': nivel, 'cenario': cenario, 'ok': not timeout,
                             'amostras_ms': [99] if timeout else [1, 2], 'envios': 1, 'bytes_json': 10}
                        if timeout:
                            r['erro'] = 'Condição não observada no prazo.'
                        (p/'trial.json').write_text(json.dumps(r))
            with patch.object(analyze, 'auditar', return_value={'ok': True}), \
                    patch.object(analyze, 'gerar_figuras'):
                resultado = analyze.analisar(root, root/'summary')
            s = json.loads((root/'summary/summary.json').read_text())
            self.assertEqual(resultado['invalidos'], 0)
            self.assertEqual(resultado['execucoes_validas'], 17)
            self.assertEqual(resultado['timeouts'], 1)
            self.assertEqual(len(s['timeouts']), 1)
            linha = next(r for r in s['linhas'] if r['nivel'] == 1. and r['cenario'] == 'crash')
            self.assertEqual(linha['tentativas'], 3)
            self.assertEqual(linha['repeticoes'], 2)
            self.assertEqual(linha['timeouts'], 1)
            self.assertEqual(linha['p50_ms'], 1.5)

            # Mesmo timeout com logs inválidos não pode ser aceito como observação experimental.
            with patch.object(analyze, 'auditar', return_value={'ok': False}), \
                    patch.object(analyze, 'gerar_figuras'):
                resultado = analyze.analisar(root, root/'invalido')
            self.assertGreater(resultado['invalidos'], 0)

class TesteFalhasObservadas(unittest.TestCase):
    def test_falhas_auditadas_preservam_celula_sem_latencias_e_nao_viram_timeout_gossip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            perfil = {'repetitions': 3, 'levels': {'heartbeat': [1.5, 3., 6.]}}
            (root/'campaign.json').write_text(json.dumps({'perfil': perfil, 'runtime': {'ambiente': 'docker'}}))
            for nivel in perfil['levels']['heartbeat']:
                for cenario in ('normal', 'crash'):
                    for rep in range(3):
                        nome = f'heartbeat-{nivel}-{cenario}-r{rep}'
                        p = root/nome; p.mkdir()
                        falha = nivel == 1.5 and cenario == 'normal'
                        r = {'run_id': nome, 'environment': 'docker', 'algoritmo': 'heartbeat',
                             'nivel': nivel, 'cenario': cenario, 'ok': not falha,
                             'amostras_ms': [999] if falha else [1, 2], 'envios': 1, 'bytes_json': 10}
                        if falha: r['erro'] = 'timed out'
                        (p/'trial.json').write_text(json.dumps(r))
            with patch.object(analyze, 'auditar', return_value={'ok': True}), patch.object(analyze, 'gerar_figuras'):
                resultado = analyze.analisar(root, root/'summary')
            resumo = json.loads((root/'summary/summary.json').read_text())
            self.assertEqual(resultado['invalidos'], 0)
            self.assertEqual(resultado['falhas'], 3)
            self.assertEqual(resultado['tentativas'], 18)
            linha = next(r for r in resumo['linhas'] if r['nivel'] == 1.5 and r['cenario'] == 'normal')
            self.assertEqual(linha['repeticoes'], 0)
            self.assertEqual(linha['tentativas'], 3)
            self.assertEqual(linha['falhas'], 3)
            self.assertEqual(linha['timeouts'], 0)
            self.assertIsNone(linha['p50_ms'])
            self.assertEqual(len(resumo['falhas']), 3)
            with patch.object(analyze, 'auditar', return_value={'ok': False}), patch.object(analyze, 'gerar_figuras'):
                self.assertGreater(analyze.analisar(root, root/'invalido')['invalidos'], 0)

    def test_manifesto_de_fonte_nao_aceita_metadado_divergente(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'campaign.json').write_text(json.dumps({'source_sha256': 'fonte-correta',
                'perfil': {'seed': 101, 'repetitions': 3, 'levels': {'lamport': [3, 5, 7]}},
                'runtime': {'ambiente': 'docker'}}))
            p=root/'lamport-3-normal-r0'; p.mkdir()
            (p/'trial.json').write_text(json.dumps({'run_id': p.name, 'ok': True, 'seed': 101,
                'environment': 'docker', 'algoritmo': 'lamport', 'nivel': 3, 'cenario': 'normal',
                'amostras_ms': [1], 'envios': 1, 'bytes_json': 10}))
            (p/'metadata.json').write_text(json.dumps({'source_sha256': 'outra-fonte'}))
            with patch.object(analyze, 'auditar', return_value={'ok': True}), patch.object(analyze, 'gerar_figuras'):
                resultado = analyze.analisar(root, root/'summary')
            self.assertEqual(resultado['execucoes_validas'], 0)


if __name__ == '__main__':
    unittest.main()
