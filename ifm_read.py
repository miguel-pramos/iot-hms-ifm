import time
from pyModbusTCP.client import ModbusClient

# --- CONFIGURAÇÕES DO DISPOSITIVO IFM ---
# Substitua pelo IP real do seu io hub / io-key na rede
IFM_IO_HUB_IP = "192.168.10.250"  
MODBUS_PORT = 502
START_ADDRESS = 0    # Endereço inicial de leitura (equivalente ao -r)
REGISTERS_COUNT = 10 # Quantidade de registradores a ler (equivalente ao -c)

def conectar_e_ler():
    # Inicializa o cliente Modbus TCP
    cliente = ModbusClient(host=IFM_IO_HUB_IP, port=MODBUS_PORT, unit_id=1,auto_open=True)
    
    print(f"Conectando ao ifm io hub em {IFM_IO_HUB_IP}:{MODBUS_PORT}...")
    
    # Lê os Holding Registers (Equivalente ao comando mbpoll -t 4:int)
    registradores = cliente.read_holding_registers(START_ADDRESS, REGISTERS_COUNT)
    
    if registradores:
        # Exibe os dados lidos de forma organizada
        for i, valor in enumerate(registradores):
            endereco_atual = START_ADDRESS + i
            print(f" 👉 Registrador [{endereco_atual}]: {valor}")
        
        # --- INSIRA SUA LÓGICA PERSONALIZADA AQUI ---
        # Exemplo: se o sensor no registrador 0 passar de 500, ativa um alerta
        # if registradores[0] > 500:
        #     executar_alerta()
        
    else:
        print("Falha na leitura: Erro de comunicação ou endereço inválido.")
        
    cliente.close()

if __name__ == "__main__":
    conectar_e_ler()
