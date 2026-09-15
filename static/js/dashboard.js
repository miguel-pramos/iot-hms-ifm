document.addEventListener("DOMContentLoaded", () => {
    const canvas = document.getElementById("graficoRealTime");
    const statusElement = document.getElementById("statusConexao");
    const valorAtualElement = document.getElementById("valorAtual");
    const metricE2E = document.getElementById("metricE2E");
    const metricRtt = document.getElementById("metricRtt");
    const metricModbusRead = document.getElementById("metricModbusRead");
    const metricModbusWrite = document.getElementById("metricModbusWrite");
    const metricCycle = document.getElementById("metricCycle");
    const metricRate = document.getElementById("metricRate");
    const storageKey = "ifm-dashboard-state";

    if (!canvas || !statusElement || !valorAtualElement || !metricE2E || !metricRtt || !metricModbusRead || !metricModbusWrite || !metricCycle || !metricRate || typeof Chart === "undefined" || typeof io === "undefined") {
        return;
    }

    const maxPoints = 120;
    const maxSamples = 120;
    const startedAt = Date.now();
    let eventCount = 0;
    const samples = {
        e2e: [],
        rtt: [],
        modbusRead: [],
        modbusWrite: [],
        cycle: []
    };

    function trimSeries(labels, values) {
        const excess = Math.max(labels.length, values.length) - maxPoints;

        if (excess <= 0) {
            return { labels, values };
        }

        return {
            labels: labels.slice(excess),
            values: values.slice(excess)
        };
    }

    function loadState() {
        try {
            const rawState = localStorage.getItem(storageKey);
            if (!rawState) {
                return { labels: [], values: [] };
            }

            const parsedState = JSON.parse(rawState);
            const trimmedState = trimSeries(
                Array.isArray(parsedState.labels) ? parsedState.labels : [],
                Array.isArray(parsedState.values) ? parsedState.values : []
            );

            return {
                labels: trimmedState.labels,
                values: trimmedState.values,
                lastValue: parsedState.lastValue
            };
        } catch {
            return { labels: [], values: [] };
        }
    }

    function trimSamples(values) {
        if (values.length <= maxSamples) {
            return values;
        }

        return values.slice(values.length - maxSamples);
    }

    function addSample(bucket, value) {
        if (typeof value !== "number" || Number.isNaN(value)) {
            return;
        }

        samples[bucket].push(value);
        samples[bucket] = trimSamples(samples[bucket]);
    }

    function percentile(values, p) {
        if (!values.length) {
            return null;
        }

        const sorted = [...values].sort((a, b) => a - b);
        const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
        return sorted[index];
    }

    function formatLatency(values) {
        const p50 = percentile(values, 50);
        const p95 = percentile(values, 95);

        if (p50 === null || p95 === null) {
            return "--";
        }

        return `${p50.toFixed(1)} ms p50 | ${p95.toFixed(1)} ms p95`;
    }

    function updateTelemetryCards() {
        metricE2E.textContent = formatLatency(samples.e2e);
        metricRtt.textContent = formatLatency(samples.rtt);
        metricModbusRead.textContent = formatLatency(samples.modbusRead);
        metricModbusWrite.textContent = formatLatency(samples.modbusWrite);
        metricCycle.textContent = formatLatency(samples.cycle);

        const elapsedSeconds = Math.max((Date.now() - startedAt) / 1000, 1);
        metricRate.textContent = `${(eventCount / elapsedSeconds).toFixed(2)} eventos/s`;
    }

    function saveState(labels, values, lastValue) {
        try {
            const trimmedState = trimSeries(labels, values);
            localStorage.setItem(storageKey, JSON.stringify({
                labels: trimmedState.labels,
                values: trimmedState.values,
                lastValue
            }));
        } catch {
            // Ignora falhas de armazenamento local para não quebrar o dashboard.
        }
    }

    const storedState = loadState();

    const chartTextColor = "#dbe7f5";
    const chartGridColor = "rgba(148, 163, 184, 0.18)";
    const chart = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
            labels: storedState.labels,
            datasets: [{
                label: "Valor do Sensor (Modbus)",
                data: storedState.values,
                borderColor: "#ff6600",
                backgroundColor: "rgba(255, 102, 0, 0.12)",
                borderWidth: 2,
                tension: 0.3,
                fill: true,
                pointRadius: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: {
                    display: true,
                    labels: {
                        color: chartTextColor,
                        boxWidth: 14,
                        usePointStyle: true
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: chartGridColor
                    },
                    ticks: {
                        color: chartTextColor,
                        maxRotation: 45,
                        minRotation: 45
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: chartGridColor
                    },
                    ticks: {
                        color: chartTextColor
                    }
                }
            }
        }
    });

    if (typeof storedState.lastValue !== "undefined") {
        valorAtualElement.textContent = `Valor atual: ${storedState.lastValue}`;
    }

    const socket = io({
        transports: ["websocket", "polling"],
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000
    });
    const probeIntervalMs = 5000;
    let probeTimer = null;

    function setStatus(text, kind) {
        statusElement.textContent = text;
        statusElement.classList.remove("status-online", "status-offline");
        statusElement.classList.add(kind === "online" ? "status-online" : "status-offline");
    }

    function sendLatencyProbe() {
        if (!socket.connected) {
            return;
        }

        const probeStart = performance.now();
        socket.emit("latency_probe", { client_sent_perf_ms: probeStart }, (response) => {
            if (!response) {
                return;
            }

            const rttMs = performance.now() - probeStart;
            addSample("rtt", rttMs);
            updateTelemetryCards();
        });
    }

    probeTimer = window.setInterval(sendLatencyProbe, probeIntervalMs);

    socket.on("connect", () => {
        setStatus("Conectado ao servidor", "online");
        sendLatencyProbe();
    });

    socket.on("disconnect", () => {
        setStatus("Conexão perdida", "offline");
    });

    socket.on("connect_error", () => {
        setStatus("Falha ao conectar", "offline");
    });

    socket.on("novo_dado", (dados) => {
        if (!dados || typeof dados.tempo === "undefined" || typeof dados.valor === "undefined") {
            return;
        }

        eventCount += 1;

        chart.data.labels.push(dados.tempo);
        chart.data.datasets[0].data.push(dados.valor);

        if (chart.data.labels.length > maxPoints) {
            chart.data.labels.shift();
            chart.data.datasets[0].data.shift();
        }

        valorAtualElement.textContent = `Valor atual: ${dados.valor}`;

        if (typeof dados.server_emit_epoch_ms === "number") {
            addSample("e2e", Date.now() - dados.server_emit_epoch_ms);
        }

        addSample("modbusRead", Number(dados.modbus_read_ms));
        addSample("modbusWrite", Number(dados.modbus_write_ms));
        addSample("cycle", Number(dados.cycle_ms));

        saveState(chart.data.labels, chart.data.datasets[0].data, dados.valor);
        chart.update();
        updateTelemetryCards();
    });

    updateTelemetryCards();
});
