"""Auditoria causal e de integridade; convergência é verificada pelos cenários."""

import argparse
import hashlib
import json
from pathlib import Path


def auditar(pasta):
    pasta = Path(pasta)
    erros = []
    try:
        meta = json.loads((pasta / "metadata.json").read_text())
        nomes = meta["nodes"]
        if not isinstance(nomes, list) or len(set(nomes)) < 3:
            raise ValueError("Esperados pelo menos três nós distintos.")
        eventos = []
        grupos = {}
        for nome in nomes:
            arquivo = pasta / nome / "logs" / "events.jsonl"
            dados = arquivo.read_bytes()
            hash_esperado = meta.get("log_sha256", {}).get(str(arquivo.relative_to(pasta)))
            if hash_esperado is None or hashlib.sha256(dados).hexdigest() != hash_esperado:
                erros.append(f"Hash ausente ou divergente: {nome}")
            linhas = dados.decode("utf-8").splitlines()
            if not linhas:
                erros.append(f"Log vazio: {nome}")
            anterior_no = None
            for linha in linhas:
                ev = json.loads(linha)
                if ev.get("no") != nome or ev.get("run_id") != meta["run_id"]:
                    raise ValueError("Identidade de evento incompatível com a execução.")
                for campo in ("geracao", "sequencia", "marca"):
                    if type(ev.get(campo)) is not int or ev[campo] < 1:
                        raise ValueError("Evento com contador/geração/sequência inválido.")
                if anterior_no is not None:
                    if ev["geracao"] < anterior_no["geracao"] or ev["marca"] <= anterior_no["marca"]:
                        erros.append(f"Geração/relógio regrediu entre eventos de {nome}")
                anterior_no = ev
                chave = (nome, ev["geracao"])
                grupo = grupos.setdefault(chave, [])
                if ev["sequencia"] != len(grupo) + 1:
                    erros.append(f"Sequência incompleta/duplicada em {chave}")
                if grupo and ev["marca"] <= grupo[-1]["marca"]:
                    erros.append(f"Relógio não crescente em {chave}")
                grupo.append(ev)
                eventos.append(ev)
        envios = {}
        acks = {}
        for ev in eventos:
            if ev["evento"] == "envio":
                chave = (ev["id"], ev["no"], ev["geracao"])
                if chave in envios:
                    erros.append("Envio lógico duplicado com mesmo ID.")
                envios[chave] = ev
            elif ev["evento"] == "envio_confirmacao":
                chave = (ev["id"], ev["no"], ev["geracao"], ev["marca"])
                acks[chave] = ev
        recebimentos = 0
        confirmacoes = 0
        for ev in eventos:
            if ev["evento"] == "recebimento":
                recebimentos += 1
                original = envios.get((ev["id"], ev["origem"], ev["geracao_origem"]))
                if (original is None or original.get("destino") != ev["no"]
                        or ev["marca_remota"] != original["marca"]
                        or ev["marca"] <= ev["marca_remota"]):
                    erros.append("Recebimento sem envio compatível ou causalidade violada.")
            elif ev["evento"] == "confirmacao_recebida":
                confirmacoes += 1
                ack = acks.get((ev["id"], ev["destino"], ev["geracao_remota"], ev["marca_remota"]))
                original = envios.get((ev["id"], ev["no"], ev["geracao"]))
                if ack is None or original is None or ev["marca"] <= ev["marca_remota"]:
                    erros.append("Confirmação sem envio/ACK compatível ou causalidade violada.")
        return {"ok": not erros, "erros": erros, "eventos": len(eventos),
                "envios": len(envios), "recebimentos": recebimentos,
                "confirmacoes": confirmacoes, "geracoes": len(grupos)}
    except (OSError, ValueError, KeyError, TypeError) as erro:
        return {"ok": False, "erros": erros + [str(erro)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pasta")
    args = parser.parse_args()
    resultado = auditar(args.pasta)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
