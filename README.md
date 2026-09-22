# Monitoramento IoT industrial sobre 5G privada

Sensor de distância ligado a um hub IFM IO-Link, lido por Modbus TCP, com
dashboard em tempo real, acionamento de torre de LED e instrumentação de
latência ponta a ponta — pensado para comparar o mesmo sensor rodando sobre
Ethernet, Wi-Fi e uma rede 5G privada (Open5GS + UERANSIM, configs em
`5g-slicing/`).

```
hub IFM IO-Link ──Modbus TCP──> app.py ──Socket.IO──> dashboard (Chart.js)
   (sensor +          │                                    navegador
    torre LED) <──────┘ escrita da torre

                      bench/bench.py  ──> CSV ──> bench/bench_plot.py ──> PNG
                      (mesmo ciclo, sem Flask: mede sem contaminar)
```

O bench reproduz exatamente o ciclo de leitura/escrita do dashboard, sem Flask
nem Socket.IO, para medir latência de Modbus sem o overhead do servidor web.

## Requisitos

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) para o ambiente e as dependências
- `make`
- Hardware opcional: hub IFM na rede (default `192.168.10.250:502`).
  Sem ele, `sim_ifm.py` faz o papel do hub.

```bash
make sync
```

## Começando sem hardware

O simulador serve os mesmos registradores do hub (4002 do sensor, 2101–2103 da
torre) com uma onda triangular de 0 a 240 mm que percorre todos os níveis.

```bash
# comparativo completo: sobe o simulador, roda os dois modos, gera os gráficos
make demo
```

Saída em `bench/bench-out/`: dois CSVs, nove PNGs e uma tabela em markdown
pronta para colar em slide.

Para ver o dashboard rodando contra o simulador:

```bash
make app-sim          # simulador + Flask juntos, http://localhost:5000
```

## Com o hardware

```bash
make bench HOST=192.168.10.250 PORT=502 LABEL=ethernet
make bench HOST=192.168.10.250 PORT=502 LABEL=5g
make plot             # compara todos os CSVs de bench/bench-out/
```

O `--label` de cada run vira a série nos gráficos comparativos, então basta um
rótulo por caminho de rede.

Dashboard contra o hub real:

```bash
make app HOST=192.168.10.250 PORT=502
```

## Alvos do Makefile

| alvo | o que faz |
|---|---|
| `make sync` | instala as dependências no `.venv` |
| `make sim` | sobe só o simulador, em primeiro plano |
| `make demo` | simulador + os dois modos de conexão + gráficos |
| `make bench` | um run contra `HOST`/`PORT`, rotulado por `LABEL` |
| `make bench-live` | run curto e verboso, para rodar ao vivo |
| `make plot` | gráficos e tabela markdown de todos os CSVs |
| `make app` | dashboard apontado para `HOST`/`PORT` |
| `make app-sim` | simulador e dashboard juntos |
| `make clean` | apaga `bench/bench-out/` |

Variáveis sobrescritíveis: `HOST` `PORT` `SAMPLES` `INTERVAL` `WARMUP` `OUTDIR`
`RATE` `SEED` `LABEL`.

```bash
make demo SAMPLES=300 INTERVAL=0.05      # 300 amostras a 20 Hz
```

## Ritmo da apresentação

600 amostras a 10 Hz levam 60 s — tempo demais de tela parada ao vivo.

- **Antes**: `make demo` com os valores default. Esses são os números oficiais,
  e os PNGs ficam prontos.
- **Ao vivo**: `make bench-live` (200 amostras a 20 Hz = 10 s). Sem `--quiet`,
  então o log mostra cada escrita na torre acontecendo.

## KPI medidos

Cada amostra vai para o CSV com `modbus_read_ms`, `modbus_write_ms`,
`cycle_ms`, valor do sensor, nível da torre e sucesso da leitura. No fim o
bench imprime min, média, p50, p95, p99, max, jitter, taxa de perda e
eventos/s.

Dois jitters são reportados, porque são coisas diferentes: o desvio-padrão da
latência e a média de |Δ| entre amostras consecutivas (IPDV).

### Resultado: o custo do `auto_close`

`app.py` criava o cliente com `auto_close=True`, fechando o TCP a cada
operação e pagando um handshake por ciclo. A flag `--keep-open` do bench mede
os dois modos. Loopback, 560 amostras a 10 Hz, `modbus_read_ms`:

| modo | p50 | p95 | p99 | jitter σ |
|---|---:|---:|---:|---:|
| `auto_close=True` | 1.981 | 2.767 | 3.058 | 0.598 |
| `auto_close=False` | 1.031 | 1.770 | 2.207 | 0.467 |

O custo é de um RTT extra por operação. Em loopback isso é ~1 ms; sobre 5G,
onde o RTT é de dezenas de ms, a diferença escala junto — o número absoluto
precisa vir do run real.

## Torre de LED

5 segmentos, verdes, acendendo de baixo para cima. Zona morta de 15 mm; os
225 mm úteis se dividem em cinco faixas iguais:

| nível | distância (mm) | segmentos |
|---|---|---|
| 0 | 0–14 | apagada |
| 1 | 15–59 | 1 |
| 2 | 60–104 | 2 |
| 3 | 105–149 | 3 |
| 4 | 150–194 | 4 |
| 5 | 195–240 | 5 |

A ordem física de acendimento está declarada em `TORRE_SEGMENTOS`
(`ifm_core.py`) — os quatro primeiros segmentos vêm do mapeamento validado na
bancada; **o quinto (byte baixo do registrador 2104) é inferido e ainda
precisa de conferência no hardware.**

## Arquivos

| caminho | o que é |
|---|---|
| `app.py` | dashboard Flask + Socket.IO |
| `ifm_core.py` | constantes, cálculo de nível e cliente Modbus (sem Flask) |
| `sim_ifm.py` | simulador Modbus TCP do hub |
| `bench/bench.py` | bench de KPI headless |
| `bench/bench_plot.py` | gráficos e tabela comparativa |
| `ifm_read.py` | leitura avulsa de registradores, para inspeção |
| `5g-slicing/` | configs de Open5GS e UERANSIM (2 slices) |
| `TUTORIAL_MODBUS.md` | acesso ao hub pelo terminal (`mbpoll`), troubleshooting |

## Variáveis de ambiente

`app.py` e `ifm_core.py` leem: `IFM_IP`, `IFM_PORT`, `IFM_UNIT_ID`,
`POLL_INTERVAL`, `RECONNECT_DELAY`, `MODBUS_TIMEOUT`.

## Limitações conhecidas

- `socketio.run()` usa o servidor de desenvolvimento do Werkzeug
  (`allow_unsafe_werkzeug=True`). Trocar por eventlet ou gevent antes de
  qualquer uso real.
- O dashboard não persiste histórico no servidor — o navegador guarda 120
  pontos em `localStorage` e perde tudo ao fechar a aba.
- Na queda do link, o loop de leitura reconecta mas não bufferiza: as amostras
  do período de indisponibilidade são perdidas.
- O quinto segmento da torre é inferido (ver acima).
