#!/usr/bin/env bash
# Cadastra os 2 subscribers no Open5GS, cada um numa slice diferente.
# Rodar dentro do container/host que tem open5gs-dbctl (pasta misc/db do open5gs).
set -euo pipefail

DBCTL=${DBCTL:-open5gs-dbctl}

# add_ue_with_slice <imsi> <key> <opc> <sst> <sd>
"$DBCTL" add_ue_with_slice 999700000000001 465B5CE8B199B49FAA5F0A2EE238A6BC E8ED289DEBA952E4283B54E88E6183CA 1 000001
"$DBCTL" add_ue_with_slice 999700000000002 465B5CE8B199B49FAA5F0A2EE238A6BC E8ED289DEBA952E4283B54E88E6183CA 1 000002
