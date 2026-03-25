#!/bin/zsh

# ============================================================
#  Forster Tools — Auphonic Automator
#  1. Extrai WAVs dos MP4s mantendo estrutura de subpastas
#  2. Envia WAVs pro Auphonic, monitora e baixa tratados
#
#  Configuração: copie config.exemplo.json → config.json
#  e preencha com suas credenciais Auphonic.
# ============================================================

SCRIPT_DIR="${0:A:h}"
CONFIG_FILE="$SCRIPT_DIR/config.json"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ config.json não encontrado."
    echo "   Copie config.exemplo.json → config.json e preencha suas credenciais."
    exit 1
fi

API_USER=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['api_user'])")
API_PASS=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['api_pass'])")
PRESET=$(python3 -c  "import json; print(json.load(open('$CONFIG_FILE'))['preset'])")
API="https://auphonic.com/api"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Forster Tools — Auphonic Automator   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# ============================================================
#  PASSO 1 — Seleciona a pasta do projeto
# ============================================================

echo -e "${YELLOW}Cole o caminho completo da pasta do projeto${NC}"
echo -e "Exemplo: /Volumes/KINGSTON/Workflow/Cliente/28. Cliente - Fevereiro 2026"
echo ""
read -r "PROJECT_PATH?Caminho: "

PROJECT_PATH="${PROJECT_PATH//\\/}"
PROJECT_PATH="${PROJECT_PATH//\"/}"
PROJECT_PATH="${PROJECT_PATH//\'/}"
PROJECT_PATH="${PROJECT_PATH% }"

if [ ! -d "$PROJECT_PATH" ]; then
    echo -e "${RED}Pasta não encontrada.${NC}"
    exit 1
fi

SOURCE_DIR="$PROJECT_PATH/1. Sony A7III - Slog2 (S-Gamut)"
EXTRACTED_DIR="$PROJECT_PATH/Áudios para tratar"
OUTPUT_DIR="$PROJECT_PATH/7. Áudios Tratados"

if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Pasta '1. Sony A7III - Slog2 (S-Gamut)' não encontrada.${NC}"
    exit 1
fi

mkdir -p "$EXTRACTED_DIR"
mkdir -p "$OUTPUT_DIR"

# ============================================================
#  PASSO 2 — Lista os MP4s encontrados
# ============================================================

echo ""
echo -e "${BLUE}Procurando MP4s em:${NC}"
echo "  $SOURCE_DIR"
echo ""

MP4_FILES=()
while IFS= read -r -d '' f; do
    MP4_FILES+=("$f")
done < <(find "$SOURCE_DIR" \( -name "*.mp4" -o -name "*.MP4" \) -print0 | sort -z)

if [ ${#MP4_FILES[@]} -eq 0 ]; then
    echo -e "${RED}Nenhum MP4 encontrado.${NC}"
    exit 1
fi

echo -e "${GREEN}${#MP4_FILES[@]} arquivo(s) encontrado(s):${NC}"
for f in "${MP4_FILES[@]}"; do
    RELATIVE="${f#$SOURCE_DIR/}"
    SIZE=$(du -sh "$f" | cut -f1)
    echo "  • $RELATIVE ($SIZE)"
done

echo ""
read -r "CONFIRM?Confirma extração e envio para o Auphonic? (s/n): "
if [[ "$CONFIRM" != "s" && "$CONFIRM" != "S" ]]; then
    echo "Cancelado."
    exit 0
fi

# ============================================================
#  PASSO 3 — Extrai WAVs mantendo estrutura de subpastas
# ============================================================

echo ""
echo -e "${BLUE}Extraindo áudios...${NC}"
echo ""

WAV_FILES=()
WAV_SUBFOLDERS=()

for FILE in "${MP4_FILES[@]}"; do
    FILENAME=$(basename "$FILE")
    NAME="${FILENAME%.*}"
    SUBDIR=$(dirname "${FILE#$SOURCE_DIR/}")

    if [ "$SUBDIR" = "." ]; then
        WAV_OUTPUT_DIR="$EXTRACTED_DIR"
    else
        WAV_OUTPUT_DIR="$EXTRACTED_DIR/$SUBDIR"
    fi
    mkdir -p "$WAV_OUTPUT_DIR"

    WAV_FILE="$WAV_OUTPUT_DIR/$NAME.wav"

    echo -n "  ⚙ $NAME ... "
    ffmpeg -i "$FILE" -vn -acodec pcm_s24le "$WAV_FILE" -y 2>/dev/null

    if [ -f "$WAV_FILE" ] && [ -s "$WAV_FILE" ]; then
        SIZE=$(du -sh "$WAV_FILE" | cut -f1)
        echo -e "${GREEN}✓ ($SIZE)${NC}"
        WAV_FILES+=("$WAV_FILE")
        WAV_SUBFOLDERS+=("$SUBDIR")
    else
        echo -e "${RED}ERRO na extração${NC}"
    fi
done

if [ ${#WAV_FILES[@]} -eq 0 ]; then
    echo -e "${RED}Nenhum WAV extraído com sucesso.${NC}"
    exit 1
fi

# ============================================================
#  PASSO 4 — Envia WAVs pro Auphonic
# ============================================================

JOB_IDS=()
JOB_NAMES=()
JOB_SUBFOLDERS=()

echo ""
echo -e "${BLUE}Enviando para o Auphonic...${NC}"
echo ""

for idx in {1..${#WAV_FILES[@]}}; do
    FILE="${WAV_FILES[$idx]}"
    SUBFOLDER="${WAV_SUBFOLDERS[$idx]}"
    FILENAME=$(basename "$FILE")
    NAME="${FILENAME%.*}"
    FILESIZE=$(du -sh "$FILE" | cut -f1)

    echo -e "  ${YELLOW}↑ $FILENAME${NC} ($FILESIZE)"

    TMPFILE=$(mktemp /tmp/auphonic_XXXXXX.json)

    curl -X POST \
        -u "$API_USER:$API_PASS" \
        -F "preset=$PRESET" \
        -F "title=$NAME" \
        -F "input_file=@$FILE" \
        "$API/simple/productions.json" \
        -o "$TMPFILE" \
        --progress-bar 2>&1 | cat

    JOB_UUID=$(python3 -c "
import json
try:
    d = json.load(open('$TMPFILE'))
    print(d['data']['uuid'])
except:
    pass
" 2>/dev/null)

    rm -f "$TMPFILE"

    if [ -z "$JOB_UUID" ]; then
        echo -e "  ${RED}ERRO ao enviar${NC}"
    else
        curl -s -X POST -u "$API_USER:$API_PASS" "$API/production/$JOB_UUID/start.json" > /dev/null
        echo -e "  ${GREEN}✓ Enviado e iniciado (job: $JOB_UUID)${NC}"
        JOB_IDS+=("$JOB_UUID")
        JOB_NAMES+=("$NAME")
        JOB_SUBFOLDERS+=("$SUBFOLDER")
    fi
    echo ""
done

if [ ${#JOB_IDS[@]} -eq 0 ]; then
    echo -e "${RED}Nenhum job criado com sucesso.${NC}"
    exit 1
fi

# ============================================================
#  PASSO 5 — Monitora o processamento
# ============================================================

echo ""
echo -e "${BLUE}Monitorando processamento... (verifica a cada 30s)${NC}"
echo ""

PENDING_IDS=("${JOB_IDS[@]}")
PENDING_NAMES=("${JOB_NAMES[@]}")
PENDING_SUBFOLDERS=("${JOB_SUBFOLDERS[@]}")
DONE_IDS=()
DONE_NAMES=()
DONE_SUBFOLDERS=()

while [ ${#PENDING_IDS[@]} -gt 0 ]; do
    sleep 30

    NEW_PENDING_IDS=()
    NEW_PENDING_NAMES=()
    NEW_PENDING_SUBFOLDERS=()

    for i in {1..${#PENDING_IDS[@]}}; do
        UUID="${PENDING_IDS[$i]}"
        NAME="${PENDING_NAMES[$i]}"
        SUBFOLDER="${PENDING_SUBFOLDERS[$i]}"

        STATUS=$(curl -s -u "$API_USER:$API_PASS" "$API/production/$UUID.json" | \
            python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['status_string'])" 2>/dev/null)

        if [ "$STATUS" = "Done" ]; then
            echo -e "  ${GREEN}✓ Pronto:${NC} $NAME"
            DONE_IDS+=("$UUID")
            DONE_NAMES+=("$NAME")
            DONE_SUBFOLDERS+=("$SUBFOLDER")
        elif [ "$STATUS" = "Error" ]; then
            echo -e "  ${RED}✗ Erro:${NC} $NAME"
        else
            echo -e "  ${YELLOW}⏳ Processando:${NC} $NAME ($STATUS)"
            NEW_PENDING_IDS+=("$UUID")
            NEW_PENDING_NAMES+=("$NAME")
            NEW_PENDING_SUBFOLDERS+=("$SUBFOLDER")
        fi
    done

    PENDING_IDS=("${NEW_PENDING_IDS[@]}")
    PENDING_NAMES=("${NEW_PENDING_NAMES[@]}")
    PENDING_SUBFOLDERS=("${NEW_PENDING_SUBFOLDERS[@]}")
done

# ============================================================
#  PASSO 6 — Baixa os arquivos tratados
# ============================================================

echo ""
echo -e "${BLUE}Baixando áudios tratados...${NC}"
echo ""

for i in {1..${#DONE_IDS[@]}}; do
    UUID="${DONE_IDS[$i]}"
    NAME="${DONE_NAMES[$i]}"
    SUBFOLDER="${DONE_SUBFOLDERS[$i]}"

    if [ "$SUBFOLDER" = "." ] || [ -z "$SUBFOLDER" ]; then
        TREATED_DIR="$OUTPUT_DIR"
    else
        TREATED_DIR="$OUTPUT_DIR/$SUBFOLDER"
    fi
    mkdir -p "$TREATED_DIR"

    FILE_URL=$(curl -s -u "$API_USER:$API_PASS" "$API/production/$UUID.json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
files = d['data'].get('output_files', [])
for f in files:
    if f.get('format', '').lower() == 'wav' or f.get('ending', '').lower() == 'wav':
        print(f['download_url'])
        break
else:
    if files:
        print(files[0]['download_url'])
" 2>/dev/null)

    if [ -z "$FILE_URL" ]; then
        echo -e "  ${RED}✗ URL não encontrada:${NC} $NAME"
        continue
    fi

    OUTPUT_FILE="$TREATED_DIR/${NAME}_auphonic.wav"
    echo -e "  ${YELLOW}↓ ${NAME}_auphonic.wav${NC}"

    curl -u "$API_USER:$API_PASS" -L -o "$OUTPUT_FILE" --progress-bar "$FILE_URL" 2>&1 | cat

    if [ -f "$OUTPUT_FILE" ] && [ -s "$OUTPUT_FILE" ]; then
        SIZE=$(du -sh "$OUTPUT_FILE" | cut -f1)
        echo -e "  ${GREEN}✓ Salvo ($SIZE)${NC}"
    else
        echo -e "  ${RED}ERRO ao baixar${NC}"
    fi
    echo ""
done

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Processo concluído!          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "Áudios tratados salvos em:"
echo -e "  $OUTPUT_DIR"
echo ""
