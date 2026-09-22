import logging
import time

from flask import Flask, render_template
from flask_socketio import SocketIO

from ifm_core import (
    POLL_INTERVAL,
    RECONNECT_DELAY,
    REGISTRADOR_LEITOR,
    calcular_nivel_torre,
    criar_cliente_modbus,
    escrever_torre,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ifm_dashboard")


app = Flask(__name__)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")


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
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)
