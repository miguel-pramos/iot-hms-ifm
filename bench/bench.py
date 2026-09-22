"""Bench de KPI headless para o hub IFM IO-Link sobre Modbus TCP.

Reproduz o ciclo de leitura/escrita de `app.py` (mesma lógica, importada de
`ifm_core.py`) sem Flask e sem Socket.IO, gravando cada amostra em CSV e
imprimindo as estatísticas de latência ao final.

Exemplos:
    uv run bench.py --host 127.0.0.1 --port 5020 --samples 600 --label ethernet
    uv run bench.py --host 127.0.0.1 --port 5020 --samples 600 --label ethernet-keepopen --keep-open
"""

import argparse
import csv
import logging
import math
import os
import statistics
import sys
import time

# Permite rodar de dentro de bench/ importando ifm_core da raiz do projeto.
RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ_PROJETO not in sys.path:
    sys.path.insert(0, RAIZ_PROJETO)

from ifm_core import (
    REGISTRADOR_LEITOR,
    calcular_nivel_torre,
    criar_cliente_modbus,
    escrever_torre,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("bench")

COLUNAS_CSV = [
    "seq",
    "epoch_ms",
    "valor",
    "modbus_read_ms",
    "modbus_write_ms",
    "cycle_ms",
    "tower_level",
    "tower_changed",
    "ok",
    "warmup",
    "label",
    "keep_open",
]

METRICAS = ("modbus_read_ms", "modbus_write_ms", "cycle_ms")


def percentil(valores_ordenados, p):
    """Percentil por interpolação linear (mesma convenção do numpy)."""
    if not valores_ordenados:
        return float("nan")
    if len(valores_ordenados) == 1:
        return valores_ordenados[0]
    posicao = (len(valores_ordenados) - 1) * (p / 100.0)
    inferior = math.floor(posicao)
    superior = math.ceil(posicao)
    if inferior == superior:
        return valores_ordenados[int(posicao)]
    peso = posicao - inferior
    return valores_ordenados[inferior] * (1 - peso) + valores_ordenados[superior] * peso


def resumir_metrica(valores):
    """min / média / p50 / p95 / p99 / max + jitter de uma série de latências."""
    if not valores:
        return None
    ordenados = sorted(valores)
    if len(valores) > 1:
        desvio_padrao = statistics.stdev(valores)
        diferencas = [abs(valores[i] - valores[i - 1]) for i in range(1, len(valores))]
        jitter_medio_consecutivo = sum(diferencas) / len(diferencas)
    else:
        desvio_padrao = 0.0
        jitter_medio_consecutivo = 0.0
    return {
        "n": len(valores),
        "min": ordenados[0],
        "media": sum(valores) / len(valores),
        "p50": percentil(ordenados, 50),
        "p95": percentil(ordenados, 95),
        "p99": percentil(ordenados, 99),
        "max": ordenados[-1],
        "jitter_desvio_padrao": desvio_padrao,
        "jitter_medio_consecutivo": jitter_medio_consecutivo,
    }


def reconectar(cliente):
    """Reconexão manual, usada no modo --keep-open (auto_close=False)."""
    try:
        cliente.close()
    except Exception:
        logger.debug("Falha ao fechar o cliente antes de reconectar", exc_info=True)
    return cliente.open()


def executar_bench(args):
    cliente = criar_cliente_modbus(
        host=args.host,
        porta=args.port,
        unit_id=args.unit_id,
        auto_close=not args.keep_open,
        timeout=args.timeout,
    )

    modo = "auto_close=False (conexão persistente)" if args.keep_open else "auto_close=True (fecha a cada operação)"
    logger.info(
        "Bench iniciado: alvo=%s:%s unit_id=%s label=%s intervalo=%.3fs modo=%s torre=%s",
        args.host,
        args.port,
        args.unit_id,
        args.label,
        args.interval,
        modo,
        "desligada" if args.no_tower else "ligada",
    )

    if args.keep_open and not cliente.open():
        logger.warning("Conexão inicial falhou; o bench segue tentando reconectar a cada ciclo")

    amostras = []
    ultimo_estado_torre = None
    sequencia = 0
    inicio_bench_ns = time.perf_counter_ns()
    limite_duracao_ns = int(args.duration * 1_000_000_000) if args.duration else None

    arquivo = open(args.output, "w", newline="", encoding="utf-8")
    escritor = csv.DictWriter(arquivo, fieldnames=COLUNAS_CSV)
    escritor.writeheader()

    try:
        while True:
            if args.samples and sequencia >= args.samples:
                break
            if limite_duracao_ns and (time.perf_counter_ns() - inicio_bench_ns) >= limite_duracao_ns:
                break

            alvo_ciclo_ns = inicio_bench_ns + int(sequencia * args.interval * 1_000_000_000)
            inicio_ciclo_ns = time.perf_counter_ns()
            epoch_ms = int(time.time() * 1000)

            valor_sensor = None
            estado_torre = None
            torre_mudou = False
            tempo_escrita_ms = None
            leitura_ok = False

            try:
                inicio_leitura_ns = time.perf_counter_ns()
                registradores = cliente.read_holding_registers(REGISTRADOR_LEITOR, 1)
                tempo_leitura_ms = (time.perf_counter_ns() - inicio_leitura_ns) / 1_000_000

                if registradores:
                    leitura_ok = True
                    valor_sensor = registradores[0]
                    estado_torre = calcular_nivel_torre(valor_sensor)
                    torre_mudou = estado_torre != ultimo_estado_torre
                    if torre_mudou and not args.no_tower:
                        torre_ok, tempo_escrita_ms = escrever_torre(cliente, estado_torre)
                        if torre_ok:
                            ultimo_estado_torre = estado_torre
                        else:
                            logger.warning("Falha ao escrever na torre de LED")
                    elif torre_mudou:
                        ultimo_estado_torre = estado_torre
                else:
                    logger.warning("Falha ao ler o hub ifm (seq=%s)", sequencia)
                    ultimo_estado_torre = None
                    if args.keep_open:
                        reconectar(cliente)
            except Exception:
                logger.exception("Erro no ciclo Modbus (seq=%s)", sequencia)
                tempo_leitura_ms = (time.perf_counter_ns() - inicio_ciclo_ns) / 1_000_000
                ultimo_estado_torre = None
                if args.keep_open:
                    reconectar(cliente)

            tempo_ciclo_ms = (time.perf_counter_ns() - inicio_ciclo_ns) / 1_000_000
            eh_warmup = sequencia < args.warmup

            amostra = {
                "seq": sequencia,
                "epoch_ms": epoch_ms,
                "valor": "" if valor_sensor is None else valor_sensor,
                "modbus_read_ms": round(tempo_leitura_ms, 3),
                # Vazio (não zero) quando não houve escrita, para não poluir a estatística.
                "modbus_write_ms": "" if tempo_escrita_ms is None else round(tempo_escrita_ms, 3),
                "cycle_ms": round(tempo_ciclo_ms, 3),
                "tower_level": "" if estado_torre is None else estado_torre,
                "tower_changed": torre_mudou,
                "ok": leitura_ok,
                "warmup": eh_warmup,
                "label": args.label,
                "keep_open": args.keep_open,
            }
            escritor.writerow(amostra)
            amostras.append(amostra)
            sequencia += 1

            # Agenda ancorada no início do bench, para não acumular deriva.
            espera_s = (alvo_ciclo_ns + int(args.interval * 1_000_000_000) - time.perf_counter_ns()) / 1_000_000_000
            if espera_s > 0:
                time.sleep(espera_s)
    except KeyboardInterrupt:
        logger.info("Bench interrompido pelo usuário na amostra %s", sequencia)
    finally:
        arquivo.close()
        try:
            cliente.close()
        except Exception:
            logger.debug("Falha ao fechar o cliente no encerramento", exc_info=True)

    duracao_total_s = (time.perf_counter_ns() - inicio_bench_ns) / 1_000_000_000
    return amostras, duracao_total_s


def calcular_estatisticas(amostras, duracao_total_s, intervalo):
    """Estatísticas sobre as amostras, descartando o warmup."""
    validas = [a for a in amostras if not a["warmup"]]
    total = len(validas)
    sucessos = [a for a in validas if a["ok"]]
    falhas = total - len(sucessos)

    series = {}
    for metrica in METRICAS:
        if metrica == "modbus_write_ms":
            # Só entram os ciclos em que a escrita realmente ocorreu.
            valores = [a[metrica] for a in validas if a[metrica] != ""]
        else:
            valores = [a[metrica] for a in sucessos]
        series[metrica] = resumir_metrica(valores)

    # Janela útil: do início da primeira amostra considerada até o fim da última.
    if len(validas) > 1:
        duracao_util_s = (validas[-1]["epoch_ms"] - validas[0]["epoch_ms"]) / 1000.0 + intervalo
    else:
        duracao_util_s = duracao_total_s

    return {
        "amostras_totais": len(amostras),
        "amostras_consideradas": total,
        "warmup_descartado": len(amostras) - total,
        "leituras_ok": len(sucessos),
        "leituras_falhas": falhas,
        "taxa_perda_pct": (falhas / total * 100.0) if total else 0.0,
        "escritas_torre": sum(1 for a in validas if a["modbus_write_ms"] != ""),
        "duracao_total_s": duracao_total_s,
        "taxa_efetiva_eventos_s": (len(sucessos) / duracao_util_s) if duracao_util_s > 0 else 0.0,
        "series": series,
    }


def imprimir_relatorio(args, estatisticas, caminho_csv):
    modo = "auto_close=False (keep-open)" if args.keep_open else "auto_close=True (padrão app.py)"
    linhas = []
    linhas.append("")
    linhas.append("=" * 78)
    linhas.append(f"BENCH DE KPI — label: {args.label}")
    linhas.append("=" * 78)
    linhas.append(f"Alvo................: {args.host}:{args.port} (unit_id={args.unit_id})")
    linhas.append(f"Modo de conexão.....: {modo}")
    linhas.append(f"Intervalo alvo......: {args.interval:.3f} s ({1 / args.interval:.2f} Hz)")
    linhas.append(f"Escrita na torre....: {'desligada (--no-tower)' if args.no_tower else 'ligada'}")
    linhas.append(f"Amostras............: {estatisticas['amostras_totais']} "
                  f"(consideradas {estatisticas['amostras_consideradas']}, "
                  f"warmup descartado {estatisticas['warmup_descartado']})")
    linhas.append(f"Duração total.......: {estatisticas['duracao_total_s']:.2f} s")
    linhas.append(f"Leituras ok/falhas..: {estatisticas['leituras_ok']} / {estatisticas['leituras_falhas']}")
    linhas.append(f"Taxa de perda.......: {estatisticas['taxa_perda_pct']:.3f} %")
    linhas.append(f"Escritas na torre...: {estatisticas['escritas_torre']}")
    linhas.append(f"Taxa efetiva........: {estatisticas['taxa_efetiva_eventos_s']:.2f} eventos/s")
    linhas.append(f"CSV.................: {caminho_csv}")
    linhas.append("")
    cabecalho = (f"{'métrica (ms)':<18}{'n':>6}{'min':>9}{'média':>9}{'p50':>9}"
                 f"{'p95':>9}{'p99':>9}{'max':>9}")
    linhas.append(cabecalho)
    linhas.append("-" * len(cabecalho))
    for metrica in METRICAS:
        resumo = estatisticas["series"][metrica]
        if not resumo:
            linhas.append(f"{metrica:<18}{'(sem amostras)':>60}")
            continue
        linhas.append(
            f"{metrica:<18}{resumo['n']:>6}{resumo['min']:>9.3f}{resumo['media']:>9.3f}"
            f"{resumo['p50']:>9.3f}{resumo['p95']:>9.3f}{resumo['p99']:>9.3f}{resumo['max']:>9.3f}"
        )
    linhas.append("")
    linhas.append("Jitter (duas definições distintas):")
    linhas.append(f"{'métrica (ms)':<18}{'desvio-padrão':>16}{'média |Δ consec.|':>20}")
    linhas.append("-" * 54)
    for metrica in METRICAS:
        resumo = estatisticas["series"][metrica]
        if not resumo:
            continue
        linhas.append(
            f"{metrica:<18}{resumo['jitter_desvio_padrao']:>16.3f}"
            f"{resumo['jitter_medio_consecutivo']:>20.3f}"
        )
    linhas.append("=" * 78)
    print("\n".join(linhas))


def analisar_argumentos(argv=None):
    parser = argparse.ArgumentParser(description="Bench de KPI Modbus TCP do hub IFM IO-Link")
    parser.add_argument("--host", default=os.getenv("IFM_IP", "127.0.0.1"), help="IP do hub/simulador")
    parser.add_argument("--port", type=int, default=int(os.getenv("IFM_PORT", "5020")), help="Porta Modbus TCP")
    parser.add_argument("--unit-id", type=int, default=int(os.getenv("IFM_UNIT_ID", "1")), help="Unit ID Modbus")
    parser.add_argument("--samples", type=int, default=None, help="Número de amostras (default: 300 se --duration não for usado)")
    parser.add_argument("--duration", type=float, default=None, help="Duração em segundos (pode ser combinada com --samples)")
    parser.add_argument("--interval", type=float, default=0.1, help="Intervalo entre ciclos em segundos (default: 0.1 = 10 Hz)")
    parser.add_argument("--timeout", type=float, default=3.0, help="Timeout Modbus em segundos (default: 3.0)")
    parser.add_argument("--output", default=None, help="Caminho do CSV (default: bench-out/bench_<label>_<timestamp>.csv)")
    parser.add_argument("--label", default="sem-rotulo", help="Rótulo do caminho de rede (ethernet / wifi / 5g)")
    parser.add_argument("--no-tower", action="store_true", help="Só leitura, sem escrever na torre de LED")
    parser.add_argument("--keep-open", action="store_true", help="Conexão TCP persistente (auto_close=False)")
    parser.add_argument("--warmup", type=int, default=0, help="Descarta as primeiras N amostras das estatísticas")
    parser.add_argument("--quiet", action="store_true", help="Reduz o log para WARNING (recomendado em runs longas)")
    args = parser.parse_args(argv)

    if args.samples is None and args.duration is None:
        args.samples = 300
    if args.interval <= 0:
        parser.error("--interval precisa ser maior que zero")
    if args.warmup < 0:
        parser.error("--warmup não pode ser negativo")

    if args.output is None:
        carimbo = time.strftime("%Y%m%d-%H%M%S")
        args.output = os.path.join("bench-out", f"bench_{args.label}_{carimbo}.csv")
    diretorio = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(diretorio, exist_ok=True)
    return args


def principal(argv=None):
    args = analisar_argumentos(argv)
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    amostras, duracao_total_s = executar_bench(args)
    if not amostras:
        logger.error("Nenhuma amostra coletada")
        return 1

    estatisticas = calcular_estatisticas(amostras, duracao_total_s, args.interval)
    imprimir_relatorio(args, estatisticas, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
