"""Gera um Compose com número configurável de nós e volumes separados."""

import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nodes',type=int,default=3);p.add_argument('--output',default='compose.generated.json')
    p.add_argument('--base-port',type=int,default=8001)
    a=p.parse_args()
    if not 3<=a.nodes<=32 or not 1024<=a.base_port<=65536-a.nodes:p.error('Faixa de nós/portas inválida')
    peers={}
    for i in range(a.nodes):peers[f'no-{i+1}']=f'http://node{i+1}:8000'
    services={};volumes={}
    for i in range(a.nodes):
        nome=f'node{i+1}';volume=f'dados-{nome}';volumes[volume]={}
        services[nome]={'build':'.','image':'mc714-trabalho2:dev',
            'environment':{'NODE_ID':f'no-{i+1}','PORT':'8000','PEERS':json.dumps(peers),
                           'DATA_DIR':'/dados','LOG_DIR':'/logs','RUN_ID':'gerado'},
            'ports':[f'127.0.0.1:{a.base_port+i}:8000'],
            'volumes':[f'{volume}:/dados',f'./results/dev/no-{i+1}/logs:/logs']}
    Path(a.output).write_text(json.dumps({'name':'mc714-trabalho2','services':services,'volumes':volumes},indent=2))
    print(a.output)


if __name__=='__main__':main()
