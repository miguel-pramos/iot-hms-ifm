"""Gráficos e comparação dos CSVs gerados por `bench.py`.

Lê um ou mais CSVs, salva os PNGs em disco (backend Agg, sem abrir janela) e
imprime uma tabela de comparação em markdown pronta para colar em slide.

Exemplo:
    uv run bench_plot.py bench-out/*.csv --outdir bench-out --metric modbus_read_ms
"""

import argparse
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (precisa vir depois do backend)

from bench import METRICAS, percentil, resumir_metrica  # noqa: E402

# Ordem fixa de cores (slots categóricos validados). Nunca reciclar a ordem:
# com mais rótulos do que cores, os slots seguintes entram na sequência.
CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
TINTA_PRIMARIA = "#1c1c1a"
TINTA_SECUNDARIA = "#5c5c58"
COR_GRADE = "#e4e4e0"
COR_FUNDO = "#fcfcfb"

NOMES_METRICAS = {
    "modbus_read_ms": "latência de leitura Modbus (ms)",
    "modbus_write_ms": "latência de escrita na torre (ms)",
    "cycle_ms": "duração do ciclo (ms)",
}


def carregar_csv(caminho):
    """Lê um CSV do bench e devolve (rotulo, lista de amostras)."""
    with open(caminho, newline="", encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))

    amostras = []
    for linha in linhas:
        if linha.get("warmup", "False") == "True":
            continue
        amostra = {
            "seq": int(linha["seq"]),
            "epoch_ms": int(linha["epoch_ms"]),
            "ok": linha["ok"] == "True",
            "keep_open": linha.get("keep_open", "") == "True",
        }
        for metrica in METRICAS:
            bruto = linha.get(metrica, "")
            amostra[metrica] = float(bruto) if bruto not in ("", None) else None
        amostras.append(amostra)

    rotulo = linhas[0].get("label") if linhas else None
    if not rotulo:
        rotulo = os.path.splitext(os.path.basename(caminho))[0]
    return rotulo, amostras


def extrair_serie(amostras, metrica):
    """Valores válidos da métrica (escrita só conta quando de fato ocorreu)."""
    if metrica == "modbus_write_ms":
        return [a[metrica] for a in amostras if a[metrica] is not None]
    return [a[metrica] for a in amostras if a["ok"] and a[metrica] is not None]


def preparar_eixo(eixo, titulo, rotulo_x, rotulo_y):
    eixo.set_title(titulo, color=TINTA_PRIMARIA, fontsize=11, loc="left", pad=10)
    eixo.set_xlabel(rotulo_x, color=TINTA_SECUNDARIA, fontsize=9)
    eixo.set_ylabel(rotulo_y, color=TINTA_SECUNDARIA, fontsize=9)
    eixo.grid(True, color=COR_GRADE, linewidth=0.8, alpha=0.9)
    eixo.set_axisbelow(True)
    for lado in ("top", "right"):
        eixo.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        eixo.spines[lado].set_color(COR_GRADE)
    eixo.tick_params(colors=TINTA_SECUNDARIA, labelsize=9)
    eixo.set_facecolor(COR_FUNDO)


def salvar(figura, caminho):
    figura.tight_layout()
    figura.savefig(caminho, dpi=150, facecolor=COR_FUNDO)
    plt.close(figura)
    print(f"PNG salvo: {caminho}")


def grafico_serie_temporal(conjuntos, metrica, caminho):
    figura, eixo = plt.subplots(figsize=(10, 4.2), facecolor=COR_FUNDO)
    for indice, (rotulo, amostras) in enumerate(conjuntos):
        if metrica == "modbus_write_ms":
            pontos = [(a["seq"], a[metrica]) for a in amostras if a[metrica] is not None]
        else:
            pontos = [(a["seq"], a[metrica]) for a in amostras if a["ok"] and a[metrica] is not None]
        if not pontos:
            continue
        eixo.plot(
            [p[0] for p in pontos],
            [p[1] for p in pontos],
            color=CORES[indice % len(CORES)],
            linewidth=1.4,
            label=rotulo,
        )
    preparar_eixo(eixo, f"Série temporal — {NOMES_METRICAS.get(metrica, metrica)}", "amostra (seq)", "ms")
    if len(conjuntos) >= 2:
        eixo.legend(frameon=False, fontsize=9, labelcolor=TINTA_SECUNDARIA)
    salvar(figura, caminho)


def grafico_histograma_cdf(conjuntos, metrica, caminho):
    figura, (eixo_hist, eixo_cdf) = plt.subplots(1, 2, figsize=(12, 4.2), facecolor=COR_FUNDO)
    for indice, (rotulo, amostras) in enumerate(conjuntos):
        valores = extrair_serie(amostras, metrica)
        if not valores:
            continue
        cor = CORES[indice % len(CORES)]
        eixo_hist.hist(valores, bins=40, color=cor, alpha=0.55, label=rotulo, edgecolor=COR_FUNDO, linewidth=0.6)
        ordenados = sorted(valores)
        acumulada = [(i + 1) / len(ordenados) * 100 for i in range(len(ordenados))]
        eixo_cdf.plot(ordenados, acumulada, color=cor, linewidth=1.4, label=rotulo)
    preparar_eixo(eixo_hist, f"Histograma — {NOMES_METRICAS.get(metrica, metrica)}", "ms", "amostras")
    preparar_eixo(eixo_cdf, f"CDF — {NOMES_METRICAS.get(metrica, metrica)}", "ms", "% das amostras <= x")
    if len(conjuntos) >= 2:
        eixo_hist.legend(frameon=False, fontsize=9, labelcolor=TINTA_SECUNDARIA)
        eixo_cdf.legend(frameon=False, fontsize=9, labelcolor=TINTA_SECUNDARIA)
    salvar(figura, caminho)


def grafico_barras_percentis(conjuntos, metrica, caminho):
    percentis = [50, 95, 99]
    figura, eixo = plt.subplots(figsize=(9, 4.6), facecolor=COR_FUNDO)
    largura_grupo = 0.78
    largura_barra = largura_grupo / max(1, len(conjuntos))

    for indice, (rotulo, amostras) in enumerate(conjuntos):
        valores = sorted(extrair_serie(amostras, metrica))
        if not valores:
            continue
        alturas = [percentil(valores, p) for p in percentis]
        posicoes = [
            i - largura_grupo / 2 + largura_barra * (indice + 0.5)
            for i in range(len(percentis))
        ]
        barras = eixo.bar(
            posicoes,
            alturas,
            width=largura_barra * 0.92,  # folga de ~2px entre barras vizinhas
            color=CORES[indice % len(CORES)],
            label=rotulo,
        )
        # Rótulo direto em cada barra (também atende o requisito de relevo de contraste).
        for barra, altura in zip(barras, alturas):
            eixo.annotate(
                f"{altura:.2f}",
                (barra.get_x() + barra.get_width() / 2, altura),
                textcoords="offset points",
                xytext=(0, 3),
                ha="center",
                fontsize=8,
                color=TINTA_SECUNDARIA,
            )

    eixo.set_xticks(range(len(percentis)))
    eixo.set_xticklabels([f"p{p}" for p in percentis])
    preparar_eixo(eixo, f"Percentis por caminho de rede — {NOMES_METRICAS.get(metrica, metrica)}", "", "ms")
    eixo.grid(axis="x", visible=False)
    # Folga no topo para os rótulos diretos não encostarem na legenda.
    eixo.set_ylim(top=eixo.get_ylim()[1] * 1.15)
    if len(conjuntos) >= 2:
        eixo.legend(frameon=False, fontsize=9, labelcolor=TINTA_SECUNDARIA, loc="upper left")
    salvar(figura, caminho)


def tabela_markdown(conjuntos, metrica):
    cabecalho = (
        "| caminho | n | min | média | p50 | p95 | p99 | max | jitter σ | jitter Δ méd. | perda % | eventos/s |"
    )
    separador = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    linhas = [f"**{NOMES_METRICAS.get(metrica, metrica)}**", "", cabecalho, separador]

    for rotulo, amostras in conjuntos:
        valores = extrair_serie(amostras, metrica)
        resumo = resumir_metrica(valores)
        if not resumo:
            linhas.append(f"| {rotulo} | 0 | — | — | — | — | — | — | — | — | — | — |")
            continue
        total = len(amostras)
        falhas = sum(1 for a in amostras if not a["ok"])
        perda = falhas / total * 100 if total else 0.0
        duracao_s = (amostras[-1]["epoch_ms"] - amostras[0]["epoch_ms"]) / 1000.0
        eventos_s = (total - falhas) / duracao_s if duracao_s > 0 else float("nan")
        linhas.append(
            f"| {rotulo} | {resumo['n']} | {resumo['min']:.3f} | {resumo['media']:.3f} | "
            f"{resumo['p50']:.3f} | {resumo['p95']:.3f} | {resumo['p99']:.3f} | {resumo['max']:.3f} | "
            f"{resumo['jitter_desvio_padrao']:.3f} | {resumo['jitter_medio_consecutivo']:.3f} | "
            f"{perda:.2f} | {eventos_s:.2f} |"
        )
    return "\n".join(linhas)


def principal(argv=None):
    parser = argparse.ArgumentParser(description="Gráficos e comparação dos CSVs do bench de KPI")
    parser.add_argument("csvs", nargs="+", help="Um ou mais CSVs gerados por bench.py")
    parser.add_argument("--outdir", default="bench-out", help="Diretório de saída dos PNGs (default: bench-out)")
    parser.add_argument("--prefixo", default="kpi", help="Prefixo dos arquivos PNG (default: kpi)")
    parser.add_argument(
        "--metric",
        default="modbus_read_ms",
        choices=list(METRICAS) + ["todas"],
        help="Métrica dos gráficos (default: modbus_read_ms; 'todas' gera um conjunto por métrica)",
    )
    args = parser.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)

    conjuntos = []
    for caminho in args.csvs:
        rotulo, amostras = carregar_csv(caminho)
        if not amostras:
            print(f"Aviso: {caminho} não tem amostras válidas, ignorado", file=sys.stderr)
            continue
        conjuntos.append((rotulo, amostras))

    if not conjuntos:
        print("Nenhum CSV válido informado", file=sys.stderr)
        return 1

    metricas = list(METRICAS) if args.metric == "todas" else [args.metric]
    blocos_markdown = []
    for metrica in metricas:
        base = os.path.join(args.outdir, f"{args.prefixo}_{metrica}")
        grafico_serie_temporal(conjuntos, metrica, f"{base}_serie.png")
        grafico_histograma_cdf(conjuntos, metrica, f"{base}_hist_cdf.png")
        grafico_barras_percentis(conjuntos, metrica, f"{base}_percentis.png")
        blocos_markdown.append(tabela_markdown(conjuntos, metrica))

    print("\n" + "\n\n".join(blocos_markdown) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
