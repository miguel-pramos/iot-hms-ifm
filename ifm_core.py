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
TORRE_CODIGO_OFF = 0x00
TORRE_CODIGO_ATIVO = 0b101


def calcular_nivel_torre(distancia):
    distancia_normalizada = max(0, min(int(distancia), MAX_DISTANCIA))
    intervalo = max(1, (MAX_DISTANCIA - 15) // TORRE_NUM_NIVEIS + 1)
    nivel = distancia_normalizada // intervalo

    if TORRE_INVERTIDA:
        nivel = (TORRE_NUM_NIVEIS - 1) - nivel

    return nivel


def obter_codigo_torre(nivel):
    color = COLOR_TABLE['green']
    on = STATUS_TABLE['ON']
    color_off = COLOR_TABLE['OFF']

    all_off = (on + color_off) << 8 | (on + color_off)

    if nivel == 0:
        return {i: all_off for i in range(TORRE_NUM_REGISTERS)}
    if nivel == 1:
        return {i: all_off for i in range(1, TORRE_NUM_REGISTERS)} | {0: (on + color_off) << 8 | (on + color) }
    if nivel == 2:
        return {i: all_off for i in range(1, TORRE_NUM_REGISTERS)} | {0: (on + color) << 8 | (on + color) }
    if nivel == 3:
        return {i: all_off for i in range(2, TORRE_NUM_REGISTERS)} | {0: (on + color) << 8 | (on + color), 1: (on + color) << 8 | (on + color_off) }
    if nivel == 4:
        return {i: all_off for i in range(2, TORRE_NUM_REGISTERS)} |{0: (on + color) << 8 | (on + color), 1: (on + color) << 8 | (on + color) }
    if nivel >= 5:
        return {i: (on + color) << 8 | (on + color) for i in range(TORRE_NUM_REGISTERS)}


def escrever_torre(cliente, nivel):
    sucesso = True
    codigos = obter_codigo_torre(nivel)
    logger.info("Escrita na torre: nivel=%s codigos=%s", nivel, codigos)
    inicio_escrita_ns = time.perf_counter_ns()
    for i in range(TORRE_NUM_REGISTERS):
        registrador = REGISTRADOR_TORRE + i
        if not cliente.write_single_register(registrador, codigos[i]):
            logger.warning("Falha ao escrever na torre de LED no registrador %s", registrador + 1)
            sucesso = False

    tempo_escrita_ms = (time.perf_counter_ns() - inicio_escrita_ns) / 1_000_000
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
