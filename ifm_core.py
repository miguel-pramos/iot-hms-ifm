"""Lógica compartilhada do hub IFM IO-Link (Modbus TCP).

Módulo sem dependência de Flask/Socket.IO, para poder ser importado tanto pelo
dashboard (`app.py`) quanto pelo bench headless (`bench.py`) sem efeito colateral
de criar servidor web.
"""

import logging
import os
import time

from pyModbusTCP.client import ModbusClient

logger = logging.getLogger("ifm_core")

COLOR_TABLE = {
    'OFF': 0x0,
    'blue': 0x1,
    'green': 0x2,
    'cyan': 0x3,
    'red': 0x4,
    'magenta': 0x5,
    'orange': 0x6,
    'white': 0x7,
    'yellow': 0x8,
}

STATUS_TABLE = {
    'ON': 0x70,
    'slow': 0x10,
    'medium': 0x20,
    'fast': 0x30,
    'blink': 0x40,
    'blink2': 0x50,
    'blink3': 0x60,
}

IFM_IP = os.getenv("IFM_IP", "192.168.10.250")
PORTA = int(os.getenv("IFM_PORT", "502"))
UNIT_ID = int(os.getenv("IFM_UNIT_ID", "1"))
REGISTRADOR_LEITOR = 4003 - 1
REGISTRADOR_TORRE = 2102 - 1
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "0.1"))
RECONNECT_DELAY = float(os.getenv("RECONNECT_DELAY", "1"))
TIMEOUT_MODBUS = float(os.getenv("MODBUS_TIMEOUT", "3.0"))
TORRE_INVERTIDA = False
TORRE_NUM_NIVEIS = 5
TORRE_NUM_REGISTERS = 3
MAX_DISTANCIA = 240
# Zona morta do sensor: abaixo disso a torre fica apagada (nivel 0) e a faixa
# util 15..240 mm e dividida igualmente entre os TORRE_NUM_NIVEIS segmentos.
TORRE_DISTANCIA_MIN = 15
# Ordem fisica de acendimento, do segmento de baixo para o de cima:
# (indice do registrador a partir de 2102, byte do registrador).
# Levantado na bancada acendendo um byte por vez: os 5 segmentos ocupam bytes
# consecutivos a partir do byte BAIXO de 2102. O byte alto de 2102 nao aciona
# nenhum segmento -- usa-lo como se fosse o segundo segmento deslocava todo o
# resto e deixava o quarto segmento apagado.
TORRE_SEGMENTOS = (
    (0, 'baixo'),
    (1, 'alto'),
    (1, 'baixo'),
    (2, 'alto'),
    (2, 'baixo'),
)
TORRE_CODIGO_OFF = 0x00
TORRE_CODIGO_ATIVO = 0b101


def calcular_nivel_torre(distancia):
    """Mapeia a distancia lida (mm) para o nivel da torre (0 = apagada)."""
    distancia_normalizada = max(0, min(int(distancia), MAX_DISTANCIA))

    if distancia_normalizada < TORRE_DISTANCIA_MIN:
        nivel = 0
    else:
        largura_faixa = (MAX_DISTANCIA - TORRE_DISTANCIA_MIN) / TORRE_NUM_NIVEIS
        acima_da_zona_morta = distancia_normalizada - TORRE_DISTANCIA_MIN
        nivel = min(TORRE_NUM_NIVEIS, int(acima_da_zona_morta // largura_faixa) + 1)

    if TORRE_INVERTIDA:
        nivel = TORRE_NUM_NIVEIS - nivel

    return nivel


def obter_codigo_torre(nivel):
    """Monta o valor de cada registrador da torre para acender `nivel` segmentos."""
    on = STATUS_TABLE['ON']
    cor_ligada = COLOR_TABLE['green']
    cor_apagada = COLOR_TABLE['OFF']

    nivel_limitado = max(0, min(int(nivel), TORRE_NUM_NIVEIS))
    bytes_por_registrador = {
        i: {'alto': cor_apagada, 'baixo': cor_apagada}
        for i in range(TORRE_NUM_REGISTERS)
    }

    for indice, (registrador, posicao) in enumerate(TORRE_SEGMENTOS):
        if indice < nivel_limitado:
            bytes_por_registrador[registrador][posicao] = cor_ligada

    return {
        i: (on + bytes_registrador['alto']) << 8 | (on + bytes_registrador['baixo'])
        for i, bytes_registrador in bytes_por_registrador.items()
    }


def escrever_torre(cliente, nivel):
    """Escreve os 3 registradores da torre numa unica transacao (FC16).

    Escrita registrador a registrador (FC6, `write_single_register`) e recusada
    pelo hub em parte dos bytes do process data de saida: o segmento nao acende
    e a escrita volta como falha. A escrita em bloco passa, e de quebra paga um
    round-trip por ciclo em vez de tres.
    """
    codigos = obter_codigo_torre(nivel)
    valores = [codigos[i] for i in range(TORRE_NUM_REGISTERS)]
    logger.info("Escrita na torre: nivel=%s codigos=%s", nivel, codigos)
    inicio_escrita_ns = time.perf_counter_ns()
    sucesso = bool(cliente.write_multiple_registers(REGISTRADOR_TORRE, valores))
    tempo_escrita_ms = (time.perf_counter_ns() - inicio_escrita_ns) / 1_000_000

    if not sucesso:
        logger.warning(
            "Falha ao escrever na torre de LED nos registradores %s..%s",
            REGISTRADOR_TORRE + 1,
            REGISTRADOR_TORRE + TORRE_NUM_REGISTERS,
        )

    return sucesso, tempo_escrita_ms


def criar_cliente_modbus(host=None, porta=None, unit_id=None, auto_close=True, timeout=None):
    """Cria o cliente Modbus TCP.

    `auto_close=True` reproduz o comportamento padrão de `app.py`: a conexão TCP
    é fechada a cada operação, ou seja, cada ciclo paga um handshake novo.
    `auto_close=False` mantém a conexão aberta (reconexão manual fica a cargo de
    quem chama).
    """
    return ModbusClient(
        host=IFM_IP if host is None else host,
        port=PORTA if porta is None else porta,
        unit_id=UNIT_ID if unit_id is None else unit_id,
        timeout=TIMEOUT_MODBUS if timeout is None else timeout,
        auto_open=True,
        auto_close=auto_close,
    )
