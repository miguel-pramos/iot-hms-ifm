import logging
import os
import time

from flask import Flask, render_template
from flask_socketio import SocketIO
from pyModbusTCP.client import ModbusClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ifm_dashboard")

app = Flask(__name__)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

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


def criar_cliente_modbus():
    return ModbusClient(
        host=IFM_IP,
        port=PORTA,
        unit_id=UNIT_ID,
        timeout=3.0,
        auto_open=True,
        auto_close=True,
    )


def loop_leitura_modbus():
    """Lê o registrador Modbus em segundo plano e publica os valores via Socket.IO."""
    cliente = criar_cliente_modbus()
    logger.info("Loop de leitura do ifm io hub iniciado")
    ultimo_estado_torre = None
    sequencia_eventos = 0

    while True:
        inicio_ciclo_ns = time.perf_counter_ns()
        try:
            inicio_leitura_ns = time.perf_counter_ns()
            registradores = cliente.read_holding_registers(REGISTRADOR_LEITOR, 1)
            tempo_leitura_ms = (time.perf_counter_ns() - inicio_leitura_ns) / 1_000_000

            if registradores is not None and len(registradores) > 0:
                valor_sensor = registradores[0]
                timestamp = time.strftime("%H:%M:%S")

                estado_torre = calcular_nivel_torre(valor_sensor)
                torre_mudou = estado_torre != ultimo_estado_torre
                torre_atualizada = False
                tempo_escrita_ms = 0.0
                if torre_mudou:
                    torre_atualizada, tempo_escrita_ms = escrever_torre(cliente, estado_torre)
                    if torre_atualizada:
                        ultimo_estado_torre = estado_torre
                        logger.info("Torre atualizada: sensor=%s nivel=%s", valor_sensor, estado_torre)
                    else:
                        logger.warning("Falha ao escrever na torre de LED")
                fim_ciclo_ns = time.perf_counter_ns()
                sequencia_eventos += 1
                socketio.emit(
                    "novo_dado",
                    {
                        "tempo": timestamp,
                        "valor": valor_sensor,
                        "sequencia": sequencia_eventos,
                        "server_emit_epoch_ms": int(time.time() * 1000),
                        "server_emit_perf_ns": fim_ciclo_ns,
                        "modbus_read_ms": round(tempo_leitura_ms, 3),
                        "modbus_write_ms": round(tempo_escrita_ms, 3),
                        "cycle_ms": round((fim_ciclo_ns - inicio_ciclo_ns) / 1_000_000, 3),
                        "tower_level": estado_torre,
                        "tower_changed": torre_mudou,
                        "tower_write_ok": torre_atualizada,
                    },
                )
            else:
                logger.warning("Falha ao ler o hub ifm")
                cliente.close()
                cliente = criar_cliente_modbus()
                ultimo_estado_torre = None
                time.sleep(RECONNECT_DELAY)
        except Exception:
            logger.exception("Erro no loop Modbus")
            cliente.close()
            cliente = criar_cliente_modbus()
            ultimo_estado_torre = None
            time.sleep(RECONNECT_DELAY)

        time.sleep(POLL_INTERVAL)


@socketio.on("latency_probe")
def latency_probe(_dados=None):
    return {
        "server_epoch_ms": int(time.time() * 1000),
        "server_perf_ns": time.perf_counter_ns(),
    }


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    socketio.start_background_task(loop_leitura_modbus)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False)
