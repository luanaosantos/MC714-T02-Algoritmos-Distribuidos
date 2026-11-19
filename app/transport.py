"""HTTP/JSON com limites de tamanho e espera explícitos."""

import json
from urllib.request import ProxyHandler, Request, build_opener

MAX_BYTES = 1024 * 1024


def post_json(url, dados, timeout=3):
    corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
    if len(corpo) > MAX_BYTES:
        raise ValueError("Mensagem excede o limite de 1 MiB.")
    pedido = Request(url, data=corpo, headers={"Content-Type": "application/json"})
    # Nós da rede do laboratório se comunicam diretamente, sem proxy HTTP.
    cliente = build_opener(ProxyHandler({}))
    with cliente.open(pedido, timeout=timeout) as resposta:
        corpo_resposta = resposta.read(MAX_BYTES + 1)
    if len(corpo_resposta) > MAX_BYTES:
        raise ValueError("Resposta excede o limite de 1 MiB.")
    resultado = json.loads(corpo_resposta)
    if not isinstance(resultado, dict):
        raise ValueError("Resposta deve ser um objeto JSON.")
    return resultado
