#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# <xbar.title>Fila de Edição - FORSTER</xbar.title>
# <xbar.version>v1.1</xbar.version>
# <xbar.author>Samuel Forster</xbar.author>
# <xbar.desc>Mostra o próximo vídeo a entregar da Fila de Edição</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>

import re
import os
from datetime import date

FILA_PATH = os.path.expanduser("~/Forster-Vault/_Interno/Fila de Edição.md")
IGNORADOS_AUTO_PATH = os.path.expanduser("~/Forster-Vault/_Interno/.fila_ignorados.txt")
IGNORADOS_MANUAL_PATH = os.path.expanduser("~/Forster-Vault/_Interno/.fila_ignorados_manual.txt")
FILA_SCRIPT = os.path.expanduser("~/Documents/forster-aprovacoes/scripts/fila_de_edicao.py")
PYTHON_BIN = "/opt/homebrew/bin/python3"

AUTO_LINE_RE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\s+—\s+(.+)$")

MONTH_MAP = {
    "Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4,
    "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8,
    "Setembro": 9, "Outubro": 10, "Novembro": 11, "Dezembro": 12
}


def clean_text(text):
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.endswith(" -"):
        text = text[:-2].strip()
    return text


def parse_cell_tasks(cell):
    text = re.sub(r"\*\*\d+\*\*", "", cell)
    text = clean_text(text)
    return text if text else None


def parse_fila(filepath):
    if not os.path.exists(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    result = {}
    last_day_in_col = {}
    current_year = None
    current_month = None

    for line in content.split("\n"):
        line = line.strip()

        month_match = re.match(r"^##\s+(\w+)\s+(\d{4})", line)
        if month_match:
            current_month = MONTH_MAP.get(month_match.group(1))
            current_year = int(month_match.group(2))
            last_day_in_col = {}
            continue

        if not (current_month and current_year and line.startswith("|")):
            continue

        if "---" in line or re.search(r"\bSeg\b", line):
            continue

        cols = [c.strip() for c in line.split("|")]
        if cols and cols[0] == "":
            cols = cols[1:]
        if cols and cols[-1] == "":
            cols = cols[:-1]

        for col_idx, cell in enumerate(cols):
            if col_idx > 6:
                break

            day_match = re.search(r"\*\*(\d+)\*\*", cell)

            if day_match:
                day_num = int(day_match.group(1))
                try:
                    entry_date = date(current_year, current_month, day_num)
                except ValueError:
                    continue

                last_day_in_col[col_idx] = entry_date

                task = parse_cell_tasks(cell)
                if task:
                    result.setdefault(entry_date, []).append(task)

            else:
                text = clean_text(cell)
                if text:
                    prev_date = last_day_in_col.get(col_idx)
                    if prev_date:
                        result.setdefault(prev_date, []).append(text)

    return result


def parse_bloco_automatico(filepath):
    """Lê a seção '🤖 Detectado automaticamente' (gerada por fila_de_edicao.py).
    Ao contrário das tabelas manuais, itens atrasados também entram — são o
    ponto principal dessa seção (reels sem entrega que passaram da data)."""
    if not os.path.exists(filepath):
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    result = {}
    for line in content.split("\n"):
        match = AUTO_LINE_RE.match(line.strip())
        if not match:
            continue
        try:
            entry_date = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        result.setdefault(entry_date, []).append(match.group(2).strip())

    return result


def carregar_lista(filepath):
    """Lê um arquivo de chaves 'já entregue' (uma por linha), se existir."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return {linha.strip() for linha in f if linha.strip()}


def main():
    manual = parse_fila(FILA_PATH)
    automatico = parse_bloco_automatico(FILA_PATH)
    ignorados_auto = carregar_lista(IGNORADOS_AUTO_PATH)
    ignorados_manual = carregar_lista(IGNORADOS_MANUAL_PATH)
    today = date.today()

    # Cada tarefa vira (texto, veio_do_bloco_automatico). Os dois tipos ganham
    # o botão "Já entreguei" — ele só grava a marcação num arquivo de lista
    # (instantâneo, sem tocar no NAS) e o filtro abaixo já esconde o item na
    # mesma hora, sem esperar o cron do dia seguinte.
    combined = {}
    for d, tasks in manual.items():
        if d < today:
            continue
        for t in tasks:
            if f"{d.isoformat()}|{t}" in ignorados_manual:
                continue
            combined.setdefault(d, []).append((t, False))
    for d, tasks in automatico.items():
        for t in tasks:
            if t in ignorados_auto:
                continue
            combined.setdefault(d, []).append((t, True))

    upcoming = sorted(combined.items(), key=lambda x: x[0])

    if not upcoming:
        print("✅ Fila limpa")
        print("---")
        print("Nenhum vídeo pendente na fila")
        print("---")
        print(f"📂 Abrir arquivo | bash=open param1='{FILA_PATH}' terminal=false")
        return

    next_date, next_tasks = upcoming[0]
    first_task = next_tasks[0][0]
    days_left = (next_date - today).days

    if days_left < 0:
        urgency, days_str = "🔴", f"atrasado {abs(days_left)}d"
    elif days_left == 0:
        urgency, days_str = "🔴", "HOJE"
    elif days_left == 1:
        urgency, days_str = "🟡", "amanhã"
    elif days_left <= 3:
        urgency, days_str = "🟡", f"{days_left}d"
    else:
        urgency, days_str = "🟢", f"{days_left}d"

    display = first_task if len(first_task) <= 40 else first_task[:37] + "…"
    print(f"{urgency} {display} ({days_str})")
    print("---")

    weekdays_pt = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    months_pt = [
        "", "jan", "fev", "mar", "abr", "mai", "jun",
        "jul", "ago", "set", "out", "nov", "dez"
    ]

    shown = 0
    for entry_date, tasks in upcoming:
        if shown >= 20:
            remaining = sum(len(t) for _, t in upcoming) - shown
            if remaining > 0:
                print(f"… e mais {remaining} itens")
            break

        dl = (entry_date - today).days
        wd = weekdays_pt[entry_date.weekday()]
        date_str = f"{wd} {entry_date.day}/{months_pt[entry_date.month]}"

        if dl < 0:
            marker = f"🔴 Atrasado {abs(dl)}d"
        elif dl == 0:
            marker = "🔴 HOJE"
        elif dl == 1:
            marker = "🟡 Amanhã"
        elif dl <= 3:
            marker = f"🟡 {dl}d"
        else:
            marker = f"🟢 {dl}d"

        for task, is_auto in tasks:
            print(f"{marker}  {date_str}  {task} | size=13")
            chave = task.replace('\\', '\\\\').replace('"', '\\"')
            if is_auto:
                flag = '--ignorar'
            else:
                flag = '--ignorar-manual'
                chave = f"{entry_date.isoformat()}|{chave}"
            print(
                f'-- ✅ Já entreguei | bash="{PYTHON_BIN}" param1="{FILA_SCRIPT}" '
                f'param2="{flag}" param3="{chave}" terminal=false refresh=true'
            )
            shown += 1

    print("---")
    total = sum(len(t) for _, t in upcoming)
    print(f"📋 {total} vídeos pendentes | size=11")
    print("---")
    print(f"📂 Abrir Fila de Edição | bash=open param1='{FILA_PATH}' terminal=false")
    print("🔄 Atualizar agora | refresh=true")


if __name__ == "__main__":
    main()
