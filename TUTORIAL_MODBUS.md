# Tutorial: Acesso ao IFM IO-Hub via Terminal (Modbus TCP)

Tutorial rápido pra ler registradores do io-hub IFM usando Modbus TCP, direto do terminal.

## 1. Pré-requisitos

- IO-Hub na rede, com IP configurado (padrão neste projeto: `192.168.10.250`)
- Porta Modbus TCP padrão: `502`
- Terminal Linux/fish

## 2. Testar conectividade básica

Antes de qualquer coisa, confirma que o hub responde na rede:

```bash
ping -c 4 192.168.10.250
```

Testa se porta 502 está aberta:

```bash
nc -zv 192.168.10.250 502
```

## 3. Ler registradores via `mbpoll` (CLI)

Instala o `mbpoll`:

```bash
# Arch
sudo pacman -S mbpoll

# Ubuntu/Debian
sudo apt update && sudo apt install mbpoll

# Fedora
sudo dnf install mbpoll
```

Lê 10 holding registers a partir do endereço 0:

```bash
mbpoll -m tcp -a 1 -t 4 -r 1 -c 10 192.168.10.250
```

Parâmetros:
- `-m tcp` modo Modbus TCP
- `-a 1` unit id (slave id) = 1
- `-t 4` tipo de registrador = holding register (16-bit)
- `-r 1` endereço inicial (mbpoll usa base 1, equivale ao endereço 0 do protocolo)
- `-c 10` quantidade de registradores a ler

Pra leitura contínua (polling a cada 1s):

```bash
mbpoll -m tcp -a 1 -t 4 -r 1 -c 10 -l 1000 192.168.10.250
```

Pra escrever num registrador (ex: registrador 0, valor 1):

```bash
mbpoll -m tcp -a 1 -t 4 -r 1 192.168.10.250 1
```

## 4. Ler via Python (`pyModbusTCP`)

Esse repo já tem `ifm_read.py` pronto. Instala dependência:

```bash
pip install pyModbusTCP
```

Roda:

```bash
python3 ifm_read.py
```

Config no arquivo (`ifm_read.py:6-9`):

```python
IFM_IO_HUB_IP = "192.168.10.250"
MODBUS_PORT = 502
START_ADDRESS = 0
REGISTERS_COUNT = 10
```

Saída esperada:

```
Conectando ao ifm io hub em 192.168.10.250:502...
 👉 Registrador [0]: 123
 👉 Registrador [1]: 456
 ...
```

## 5. Troubleshooting

| Problema | Causa provável | Solução |
|---|---|---|
| `ping` falha | Hub fora da rede/IP errado | Confere IP no hub (display/app IFM) |
| `nc` porta fechada | Firewall ou Modbus desativado no hub | Ativa Modbus TCP na config do hub |
| `Falha na leitura` | Unit ID errado ou endereço inválido | Testa `unit_id=1` (padrão IFM), varia `START_ADDRESS` |
| Timeout | Hub ocupado por outro cliente Modbus | Só 1 conexão Modbus TCP simultânea em alguns hubs — fecha outros clientes |

## 6. Referência rápida de comandos

```bash
# ping
ping -c 4 <IP>

# checar porta
nc -zv <IP> 502

# ler com mbpoll
mbpoll -m tcp -a 1 -t 4 -r 1 -c 10 <IP>

# ler com script do projeto
python3 ifm_read.py
```
