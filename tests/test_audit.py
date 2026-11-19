import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from scripts.check_logs import auditar


class TesteAuditoria(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        self.meta = {"run_id": "r1", "nodes": ["no-1", "no-2", "no-3"], "log_sha256": {}}
        for nome in self.meta["nodes"]:
            p = self.pasta / nome / 'logs/events.jsonl'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({"run_id": "r1", "no": nome, "geracao": 1,
                                     "sequencia": 1, "marca": 1, "evento": "boot"}) + '\n')
        self.atualizar_hashes()

    def atualizar_hashes(self):
        for p in self.pasta.glob('no-*/logs/events.jsonl'):
            self.meta['log_sha256'][str(p.relative_to(self.pasta))] = hashlib.sha256(p.read_bytes()).hexdigest()
        (self.pasta/'metadata.json').write_text(json.dumps(self.meta))

    def test_logs_integralmente_consistentes_passam(self):
        self.assertTrue(auditar(self.pasta)['ok'])

    def test_participante_ausente_falha(self):
        (self.pasta/'no-3/logs/events.jsonl').unlink()
        self.assertFalse(auditar(self.pasta)['ok'])

    def test_hash_alterado_falha(self):
        with (self.pasta/'no-1/logs/events.jsonl').open('a') as f:
            f.write(' ')
        self.assertFalse(auditar(self.pasta)['ok'])

    def test_sequencia_incompleta_falha_mesmo_com_hash_valido(self):
        p=self.pasta/'no-1/logs/events.jsonl'
        ev=json.loads(p.read_text());ev.update(sequencia=2)
        p.write_text(json.dumps(ev)+'\n');self.atualizar_hashes()
        self.assertFalse(auditar(self.pasta)['ok'])

    def test_recebimento_sem_envio_falha(self):
        p=self.pasta/'no-1/logs/events.jsonl'
        ev={"run_id":"r1","no":"no-1","geracao":1,"sequencia":2,"marca":2,
            "evento":"recebimento","id":"inexistente","origem":"no-2",
            "geracao_origem":1,"marca_remota":1}
        with p.open('a') as f:f.write(json.dumps(ev)+'\n')
        self.atualizar_hashes()
        self.assertFalse(auditar(self.pasta)['ok'])

    def test_linha_truncada_falha(self):
        p=self.pasta/'no-1/logs/events.jsonl'
        with p.open('a') as f:f.write('{"evento":')
        self.atualizar_hashes()
        self.assertFalse(auditar(self.pasta)['ok'])

    def test_relogio_nao_pode_regredir_entre_geracoes(self):
        p=self.pasta/'no-1/logs/events.jsonl'
        a=json.loads(p.read_text());a['marca']=100
        b={**a,'geracao':2,'marca':1,'sequencia':1}
        p.write_text(json.dumps(a)+'\n'+json.dumps(b)+'\n');self.atualizar_hashes()
        self.assertFalse(auditar(self.pasta)['ok'])
