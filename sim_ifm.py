"""Simulador do hub IFM IO-Link exposto via Modbus TCP.

Substitui o hardware real para permitir desenvolver e demonstrar o bench de KPI
sem o equipamento físico. Serve holding registers cobrindo o registrador do
sensor de distância (4002, 0-indexed) e os três registradores da torre de LED
(2101..2103, 0-indexed).

Uso:
    uv run sim_ifm.py --host 127.0.0.1 --port 5020 --unit-id 1 --rate 20
"""

import argparse
import asyncio
import logging
import random
import time

from pymodbus.server import ModbusTcpServer
from pymodbus.simulator.simdata import DataType, SimData
from pymodbus.simulator.simdevice import SimDevice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sim_ifm")

# Mesmos endereços de ifm_core.py (0-indexed, como vão no fio).
REGISTRADOR_LEITOR = 4003 - 1
REGISTRADOR_TORRE = 2102 - 1
TORRE_NUM_REGISTERS = 3
MAX_DISTANCIA = 240
NUM_REGISTRADORES = 5000

# Códigos de função Modbus que interessam ao log de escrita.
FUNCAO_ESCRITA_UNICA = 6
FUNCAO_ESCRITA_MULTIPLA = 16
FUNCAO_HOLDING = 3


def gerar_valor_sensor(tempo_s, periodo_s, ruido):
    """Onda triangular 0..MAX_DISTANCIA com ruído.

    A forma triangular garante que o valor atravesse os 6 níveis da torre
    (`calcular_nivel_torre` devolve 0..5), subindo e descendo, para exercitar o
    caminho de escrita nos dois sentidos.
    """
    fase = (tempo_s % periodo_s) / periodo_s
    # Triângulo: sobe de 0 a 1 na primeira metade, desce na segunda.
    triangulo = 2 * fase if fase < 0.5 else 2 * (1 - fase)
    valor = triangulo * MAX_DISTANCIA + random.uniform(-ruido, ruido)
    return max(0, min(MAX_DISTANCIA, int(round(valor))))


async def tarefa_atualizar_sensor(servidor, unit_id, rate, periodo_s, ruido):
    """Atualiza o registrador do sensor na taxa configurada."""
    intervalo = 1.0 / rate
    inicio = time.perf_counter()
    ultimo_log = 0.0
    while True:
        agora = time.perf_counter() - inicio
        valor = gerar_valor_sensor(agora, periodo_s, ruido)
        await servidor.async_setValues(unit_id, FUNCAO_HOLDING, REGISTRADOR_LEITOR, [valor])
        if agora - ultimo_log >= 5.0:
            logger.info("Sensor simulado: registrador=%s valor=%s mm", REGISTRADOR_LEITOR, valor)
            ultimo_log = agora
        await asyncio.sleep(intervalo)


def criar_rastreador_pdu():
    """Devolve um callback trace_pdu que loga as escritas recebidas na torre."""

    def rastrear_pdu(entrada, pdu):
        if not entrada:
            return pdu
        codigo_funcao = getattr(pdu, "function_code", None)
        if codigo_funcao not in (FUNCAO_ESCRITA_UNICA, FUNCAO_ESCRITA_MULTIPLA):
            return pdu
        endereco = getattr(pdu, "address", None)
        registradores = getattr(pdu, "registers", None)
        if registradores is None:
            valor = getattr(pdu, "count", None)
            registradores = [valor] if valor is not None else []
        faixa_torre = range(REGISTRADOR_TORRE, REGISTRADOR_TORRE + TORRE_NUM_REGISTERS)
        alvo = "TORRE" if endereco in faixa_torre else "outro"
        logger.info(
            "Escrita recebida (%s): fc=%s registrador=%s (1-indexed %s) valores=%s",
            alvo,
            codigo_funcao,
            endereco,
            None if endereco is None else endereco + 1,
            [hex(v) if isinstance(v, int) else v for v in registradores],
        )
        return pdu

    return rastrear_pdu


async def executar(args):
    dispositivo = SimDevice(
        id=args.unit_id,
        simdata=[
            SimData(
                address=0,
                count=NUM_REGISTRADORES,
                values=0,
                datatype=DataType.REGISTERS,
            )
        ],
    )
    servidor = ModbusTcpServer(
        dispositivo,
        address=(args.host, args.port),
        trace_pdu=criar_rastreador_pdu(),
    )
    logger.info(
        "Simulador IFM ouvindo em %s:%s (unit_id=%s, sensor no registrador %s, torre em %s..%s)",
        args.host,
        args.port,
        args.unit_id,
        REGISTRADOR_LEITOR,
        REGISTRADOR_TORRE,
        REGISTRADOR_TORRE + TORRE_NUM_REGISTERS - 1,
    )
    tarefa = asyncio.create_task(
        tarefa_atualizar_sensor(servidor, args.unit_id, args.rate, args.periodo, args.ruido)
    )
    try:
        await servidor.serve_forever()
    finally:
        tarefa.cancel()


def main():
    parser = argparse.ArgumentParser(description="Simulador Modbus TCP do hub IFM IO-Link")
    parser.add_argument("--host", default="127.0.0.1", help="Endereço de escuta (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5020, help="Porta TCP (default: 5020; 502 exige root)")
    parser.add_argument("--unit-id", type=int, default=1, help="Unit ID Modbus (default: 1)")
    parser.add_argument("--rate", type=float, default=20.0, help="Hz de atualização do valor do sensor (default: 20)")
    parser.add_argument("--periodo", type=float, default=12.0, help="Período da onda triangular em segundos (default: 12)")
    parser.add_argument("--ruido", type=float, default=2.0, help="Amplitude do ruído em mm (default: 2)")
    parser.add_argument("--seed", type=int, default=None, help="Semente do ruído, para repetibilidade")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    try:
        asyncio.run(executar(args))
    except KeyboardInterrupt:
        logger.info("Simulador encerrado pelo usuário")


if __name__ == "__main__":
    main()
