# Configuracoes sobrescritiveis: make demo PORT=5021 SAMPLES=300
HOST      ?= 127.0.0.1
PORT      ?= 502
SAMPLES   ?= 600
INTERVAL  ?= 0.1
WARMUP    ?= 20
OUTDIR    ?= bench/bench-out
RATE      ?= 20
SEED      ?= 42
LABEL     ?= run
IFM_IP    ?= 192.168.10.250

BENCH = uv run bench/bench.py --host $(HOST) --port $(PORT) \
        --samples $(SAMPLES) --interval $(INTERVAL) --warmup $(WARMUP)

.DEFAULT_GOAL := help
.PHONY: help sync sim demo bench bench-live plot app app-sim clean

help: ## Lista os alvos disponiveis
	@echo "Alvos:"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'
	@echo ""
	@echo "Variaveis: HOST PORT SAMPLES INTERVAL WARMUP OUTDIR RATE SEED LABEL"

sync: ## Instala as dependencias no .venv via uv
	uv sync

$(OUTDIR):
	@mkdir -p $(OUTDIR)

sim: ## Sobe o simulador do hub IFM em primeiro plano (Ctrl-C para parar)
	uv run sim_ifm.py --host $(HOST) --port $(PORT) --rate $(RATE) --seed $(SEED)

demo: | $(OUTDIR) ## Comparativo auto_close on/off contra o simulador, com graficos
	@uv run sim_ifm.py --host $(HOST) --port $(PORT) --rate $(RATE) --seed $(SEED) \
		> $(OUTDIR)/sim.log 2>&1 & \
	SIM_PID=$$!; \
	trap "kill $$SIM_PID 2>/dev/null" EXIT; \
	sleep 2; \
	echo "== auto_close=True (comportamento de app.py) =="; \
	$(BENCH) --label autoclose --quiet --output $(OUTDIR)/autoclose.csv; \
	echo "== auto_close=False (--keep-open) =="; \
	$(BENCH) --label keepopen --keep-open --quiet --output $(OUTDIR)/keepopen.csv; \
	uv run bench/bench_plot.py $(OUTDIR)/autoclose.csv $(OUTDIR)/keepopen.csv \
		--outdir $(OUTDIR) --metric todas

bench: | $(OUTDIR) ## Um run contra HOST/PORT. Ex: make bench HOST=192.168.10.250 PORT=502 LABEL=5g
	$(BENCH) --label $(LABEL) --quiet --output $(OUTDIR)/$(LABEL).csv

bench-live: | $(OUTDIR) ## Run curto e verboso para rodar ao vivo na apresentacao
	uv run bench/bench.py --host $(HOST) --port $(PORT) \
		--samples 200 --interval 0.05 --warmup 10 --label demo \
		--output $(OUTDIR)/demo.csv

plot: ## Gera graficos e tabela markdown de todos os CSVs em OUTDIR
	uv run bench/bench_plot.py $(OUTDIR)/*.csv --outdir $(OUTDIR) --metric todas

app: ## Sobe o dashboard apontado para HOST/PORT (default: simulador)
	env IFM_IP=$(IFM_IP) IFM_PORT=$(PORT) uv run app.py

app-sim: ## Sobe simulador e dashboard juntos (Ctrl-C derruba os dois)
	@uv run sim_ifm.py --host $(HOST) --port $(PORT) --rate $(RATE) --seed $(SEED) \
		> $(OUTDIR)/sim.log 2>&1 & \
	SIM_PID=$$!; \
	trap "kill $$SIM_PID 2>/dev/null" EXIT; \
	sleep 2; \
	env IFM_IP=$(HOST) IFM_PORT=$(PORT) uv run app.py

clean: ## Apaga CSVs, PNGs e logs do bench
	rm -rf $(OUTDIR)
