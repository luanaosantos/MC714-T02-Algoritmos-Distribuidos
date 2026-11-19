"""Regressões do pipeline de evidências, sem executar Docker."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import analyze, runtime
from scripts import run_experiments


class TestePipeline(unittest.TestCase):
    def test_retomada_apos_timeout_exige_opcao_explicita_e_preserva_resultado(self):
        perfil = {'repetitions': 2, 'seed': 1, 'levels': {'gossip': [.2, .5, 1.]}}
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)/'campanha'
            def ensaio(destino, base, algoritmo, nivel, falha, perfil):
                destino.mkdir()
                timeout = destino.name == 'gossip-0.2-normal-r0'
                r = {'ok': not timeout, 'run_id': destino.name, 'algoritmo': algoritmo,
                     'nivel': nivel, 'cenario': 'crash' if falha else 'normal',
                     'seed': base['seed'], 'amostras_ms': [1]}
                if timeout:
                    r['erro'] = 'Condição não observada no prazo.'
                (destino/'trial.json').write_text(json.dumps(r))
                (destino/'metadata.json').write_text(json.dumps({'source_sha256': 'fonte'}))
                return r
            with patch.object(run_experiments, 'digest_codigo', return_value='fonte'), \
                    patch.object(run_experiments, 'ensaio', side_effect=ensaio), \
                    patch.object(run_experiments, 'auditar', return_value={'ok': True}):
                run_experiments.executar_campanha(perfil, {}, pasta, limite=1)
                with self.assertRaises(ValueError):
                    run_experiments.executar_campanha(perfil, {}, pasta, retomar=True)
                r = run_experiments.executar_campanha(perfil, {}, pasta, retomar=True, aceitar_timeouts=True)
                self.assertTrue(r['completa'])
                self.assertEqual(r['timeouts'], 1)
                self.assertFalse(json.loads((pasta/'gossip-0.2-normal-r0/trial.json').read_text())['ok'])

    def test_suspeita_durante_comando_de_crash_nao_e_descartada(self):
        from types import SimpleNamespace
        estado = {'suspeitos': []}
        def matar(alvo):
            estado['suspeitos'] = [alvo]
            return 200
        cluster = SimpleNamespace(nomes=['a', 'b', 'c'], chamar=lambda *args: estado,
                                  registrar=lambda *args, **kwargs: 100, matar=matar)
        inicio, confirmado = run_experiments.injetar_crash(cluster, 'c', ['a', 'b'], True)
        self.assertEqual((inicio, confirmado), (100, 200))
        self.assertEqual(estado['suspeitos'], ['c'])

    def test_campanha_retoma_lotes_sem_reexecutar_nem_mudar_fonte(self):
        perfil = {'repetitions': 2, 'seed': 1, 'levels': {'lamport': [3, 5, 7]}}
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)/'campanha'
            def ensaio(destino, base, algoritmo, nivel, falha, perfil):
                destino.mkdir()
                r = {'ok': True, 'run_id': destino.name, 'algoritmo': algoritmo,
                     'nivel': nivel, 'cenario': 'crash' if falha else 'normal',
                     'seed': base['seed']}
                (destino/'trial.json').write_text(json.dumps(r))
                (destino/'metadata.json').write_text(json.dumps({'source_sha256': 'fonte1'}))
                return r
            with patch.object(run_experiments, 'digest_codigo', return_value='fonte1'), \
                    patch.object(run_experiments, 'ensaio', side_effect=ensaio) as rodar, \
                    patch.object(run_experiments, 'auditar', return_value={'ok': True}):
                r = run_experiments.executar_campanha(perfil, {}, pasta, limite=3)
                self.assertFalse(r['completa'])
                self.assertEqual(rodar.call_count, 3)
                incompleto = pasta/'lamport-3-crash-r1'
                incompleto.mkdir()
                (incompleto/'diagnostico.txt').write_text('execução interrompida')
                (incompleto/'compose.run.json').write_text('{}')
                with patch.object(run_experiments, 'recuperar_compose_interrompido') as recuperar:
                    r = run_experiments.executar_campanha(perfil, {}, pasta, retomar=True)
                recuperar.assert_called_once_with(incompleto)
                self.assertTrue(r['completa'])
                self.assertEqual(rodar.call_count, 12)
                self.assertTrue(list((pasta/'interrupted').glob('*/diagnostico.txt')))
                with patch.object(run_experiments, 'digest_codigo', return_value='fonte2'):
                    with self.assertRaises(ValueError):
                        run_experiments.executar_campanha(perfil, {}, pasta, retomar=True)

    def test_ensaio_com_ambiente_ou_nivel_incompativel_e_invalido(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'campaign.json').write_text(json.dumps({
                'perfil': {'repetitions': 2, 'levels': {'lamport': [3, 5, 7]}},
                'runtime': {'ambiente': 'local-compose'}}))
            for erro in ['ambiente', 'nivel']:
                pasta = root/'lamport-3-normal-r0'
                pasta.mkdir(exist_ok=True)
                r = {'run_id': pasta.name, 'ok': True, 'environment': 'local-compose',
                     'algoritmo': 'lamport', 'cenario': 'normal', 'nivel': 3,
                     'amostras_ms': [1], 'envios': 1, 'bytes_json': 10}
                r['environment' if erro == 'ambiente' else 'nivel'] = 'outro' if erro == 'ambiente' else 5
                (pasta/'trial.json').write_text(json.dumps(r))
                with patch.object(analyze, 'auditar', return_value={'ok': True}), \
                        patch.object(analyze, 'gerar_figuras'):
                    result = analyze.analisar(root, root/'summary')
                self.assertEqual(result['execucoes_validas'], 0)

    def test_crash_nao_mede_suspeita_que_ja_existia(self):
        from types import SimpleNamespace
        cluster = SimpleNamespace(nomes=['a', 'b', 'c'],
                                  chamar=lambda *args: {'suspeitos': ['c']})
        with self.assertRaises(TimeoutError):
            run_experiments.aguardar_detector_pronto(cluster, timeout=.01)
        cluster.chamar = lambda *args: {'suspeitos': []}
        run_experiments.aguardar_detector_pronto(cluster, timeout=.1)
        cluster.chamar = lambda *args: {'suspeitos': ['c']}
        with self.assertRaises(ValueError):
            run_experiments.validar_inicio_crash(cluster, 'c', ['a', 'b'])

    def test_reinicio_compose_redescobre_porta_publicada(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(runtime.subprocess, 'check_output', return_value='{}'):
                cluster = runtime.Cluster(Path(tmp)/'ensaio', {'backend': 'compose'})
            cluster.urls['no-3'] = 'http://127.0.0.1:30001'
            with patch.object(runtime.subprocess, 'run'), \
                    patch.object(runtime.subprocess, 'check_output', return_value='127.0.0.1:30099\n'), \
                    patch.object(cluster, 'aguardar_saude') as saude:
                cluster.reiniciar('no-3')
            self.assertEqual(cluster.urls['no-3'], 'http://127.0.0.1:30099')
            saude.assert_called_once_with('no-3')

    def test_compose_usa_disco_linux_isolado_e_exporta_evidencias(self):
        with tempfile.TemporaryDirectory() as tmp:
            def resposta(cmd, **kwargs):
                if 'port' in cmd:
                    return '127.0.0.1:32123\n'
                return '{"python":"APP_PYTHON","os":"APP_OS"}' if 'exec' in cmd else '{}'
            with patch.object(runtime.subprocess, 'check_output', side_effect=resposta), \
                    patch.object(runtime.subprocess, 'run') as executar:
                cluster = runtime.Cluster(Path(tmp) / 'ensaio', {'backend': 'compose'})
                with patch.object(cluster, 'aguardar_saude'):
                    cluster.start()
                compose = json.loads(cluster.compose.read_text())
                self.assertEqual(len(compose['volumes']), 6)
                self.assertEqual(compose['services']['no-1']['volumes'],
                                 ['no-1-data:/dados', 'no-1-logs:/logs'])
                self.assertEqual(compose['services']['no-1']['ports'], ['127.0.0.1::8000'])
                self.assertEqual(cluster.urls['no-1'], 'http://127.0.0.1:32123')
                self.assertEqual(cluster.metadata['application_runtime']['python'], 'APP_PYTHON')
                cluster.stop()
                comandos = [c.args[0] for c in executar.call_args_list]
                self.assertEqual(sum(c[:2] == ['docker', 'cp'] for c in comandos), 6)
                self.assertIn('--volumes', comandos[-1])

    def test_duas_campanhas_no_mesmo_ambiente_nao_misturam_amostras(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for nome, valor in [('piloto', 1), ('ampliada', 100)]:
                pasta = root / nome
                ensaio = pasta / 'lamport-3-normal-r0'
                ensaio.mkdir(parents=True)
                (pasta / 'campaign.json').write_text(json.dumps({
                    'perfil': {'repetitions': 3, 'levels': {'lamport': [3, 5, 7]}},
                    'runtime': {'backend': 'compose', 'ambiente': 'local-compose'}}))
                (ensaio / 'trial.json').write_text(json.dumps({
                    'run_id': ensaio.name, 'ok': True, 'environment': 'local-compose',
                    'algoritmo': 'lamport', 'cenario': 'normal', 'nivel': 3,
                    'amostras_ms': [valor], 'envios': 1, 'bytes_json': 10}))
            with patch.object(analyze, 'auditar', return_value={'ok': True}), \
                    patch.object(analyze, 'gerar_figuras'):
                analyze.analisar(root, root / 'summary')
            resumo = json.loads((root / 'summary/summary.json').read_text())
            self.assertEqual(len(resumo['linhas']), 2)
            self.assertEqual({r['p50_ms'] for r in resumo['linhas']}, {1, 100})
            self.assertEqual(len(resumo['campanhas']), 2)

    def test_hardware_registra_cpu_memoria_e_limites_docker(self):
        info = runtime.hardware()
        self.assertTrue(info['cpu_model'])
        self.assertGreater(info['memory_bytes'], 0)



if __name__ == '__main__':
    unittest.main()
