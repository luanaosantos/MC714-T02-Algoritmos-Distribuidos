"""Cliente de terminal para operações e observação do catálogo."""

import argparse
import json
from urllib.parse import quote
from scripts.runtime import http


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='http://127.0.0.1:8001')
    sub=p.add_subparsers(dest='acao',required=True)
    for nome in ('health','state','catalog','event'):sub.add_parser(nome)
    get=sub.add_parser('get');get.add_argument('chave')
    put=sub.add_parser('put');put.add_argument('chave');put.add_argument('valor')
    delete=sub.add_parser('delete');delete.add_argument('chave')
    for nome in ('sync','heartbeat'):
        s=sub.add_parser(nome);s.add_argument('destino')
    send=sub.add_parser('send');send.add_argument('destino');send.add_argument('conteudo')
    f=sub.add_parser('faults');f.add_argument('json')
    a=p.parse_args()
    rota='/'+a.acao;dados=None
    if a.acao in ('put','delete'):
        rota='/put';dados={'chave':a.chave,'valor':a.valor if a.acao=='put' else None}
    elif a.acao=='get':rota='/get?chave='+quote(a.chave,safe='')
    elif a.acao=='event':dados={}
    elif a.acao in ('sync','heartbeat'):
        rota='/sync' if a.acao=='sync' else '/sync-heartbeat';dados={'destino':a.destino}
    elif a.acao=='send':dados={'destino':a.destino,'conteudo':a.conteudo}
    elif a.acao=='faults':dados=json.loads(a.json)
    try:
        print(json.dumps(http(a.url,rota,dados),ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError) as erro:
        print(json.dumps({'erro':str(erro)},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
