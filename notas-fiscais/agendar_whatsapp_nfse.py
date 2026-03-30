#!/usr/bin/env python3
"""
agendar_whatsapp_nfse.py — Agenda envio de NFS-e via WhatsApp (Forster Lembretes)

Lê ultima_emissao.json (gerado por emitir_nfs_nacional.py) e insere mensagens
com PDF anexo no agendados.json do Forster Lembretes para envio às 09:00.

Uso:
    python3 agendar_whatsapp_nfse.py                # agenda para 09:00 de hoje
    python3 agendar_whatsapp_nfse.py --horario 10:00  # agenda para 10:00
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

FUSO_BR = timezone(timedelta(hours=-3))

SCRIPT_DIR = Path(__file__).parent
ULTIMA_EMISSAO = SCRIPT_DIR / "ultima_emissao.json"
CONFIG_EMISSAO = SCRIPT_DIR / "config_emissao.json"
AGENDADOS_PATH = Path.home() / "Documents" / "forster-lembretes" / "agendados.json"

MENSAGEM_TEMPLATE = (
    "Bom dia! Segue a Nota Fiscal de Serviço referente a {competencia_fmt}.\n\n"
    "Valor: R$ {valor_fmt}\n\n"
    "Chave PIX para pagamento: 35.935.852/0001-55\n\n"
    "Qualquer dúvida, estamos à disposição. Obrigado!"
)

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]


def formatar_competencia(comp_str):
    """'2026-04' → 'abril/2026'"""
    partes = comp_str.split("-")
    mes_idx = int(partes[1]) - 1
    return f"{MESES[mes_idx]}/{partes[0]}"


def formatar_valor(valor):
    """2000.0 → '2.000,00'"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def ler_agendados():
    try:
        return json.loads(AGENDADOS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def salvar_agendados(lista):
    AGENDADOS_PATH.write_text(json.dumps(lista, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def buscar_whatsapp(apelido, config):
    """Busca número de WhatsApp do cliente no config_emissao.json."""
    emissor_nome = config.get("emissor_ativo", "")
    emissor = config.get("emissores", {}).get(emissor_nome, {})
    for cliente in emissor.get("clientes", []):
        if cliente.get("apelido", "").lower() == apelido.lower():
            return cliente.get("whatsapp")
    return None


def main():
    parser = argparse.ArgumentParser(description="Agenda envio de NFS-e via WhatsApp")
    parser.add_argument("--horario", default="09:00", help="Horário de envio HH:MM (padrão: 09:00)")
    args = parser.parse_args()

    if not ULTIMA_EMISSAO.exists():
        print("Erro: ultima_emissao.json não encontrado. Rode emitir_nfs_nacional.py primeiro.")
        sys.exit(1)

    emissao = json.loads(ULTIMA_EMISSAO.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_EMISSAO.read_text(encoding="utf-8"))
    resultados = emissao.get("resultados", [])
    competencia = emissao.get("competencia", "")

    if not resultados:
        print("Nenhum resultado de emissão encontrado.")
        sys.exit(0)

    # Monta horário de envio (hoje às HH:MM)
    hora, minuto = args.horario.split(":")
    agora = datetime.now(FUSO_BR)
    envio = agora.replace(hour=int(hora), minute=int(minuto), second=0, microsecond=0)
    if envio <= agora:
        # Se já passou do horário, agenda para daqui a 2 minutos
        envio = agora + timedelta(minutes=2)
        print(f"Horário {args.horario} já passou. Agendando para {envio.strftime('%H:%M')}.")

    agendados = ler_agendados()
    novos = 0

    for r in resultados:
        whatsapp = buscar_whatsapp(r["apelido"], config)
        if not whatsapp:
            print(f"  AVISO: Número WhatsApp não encontrado para {r['apelido']}. Pulando.")
            continue

        pdf_path = r.get("pdf_path")
        xml_path = r.get("xml_path")
        arquivos = []
        if pdf_path and Path(pdf_path).exists():
            arquivos.append(pdf_path)
        if xml_path and Path(xml_path).exists():
            arquivos.append(xml_path)

        competencia_fmt = formatar_competencia(competencia)
        valor_fmt = formatar_valor(r["valor"])

        mensagem = MENSAGEM_TEMPLATE.format(
            competencia_fmt=competencia_fmt,
            valor_fmt=valor_fmt,
        )

        item = {
            "id": f"nfse-{r['n_nfse']}-{int(agora.timestamp())}",
            "numero": whatsapp,
            "mensagem": mensagem,
            "dataEnvio": envio.isoformat(),
            "criadoEm": agora.isoformat(),
        }
        if arquivos:
            item["media"] = arquivos if len(arquivos) > 1 else arquivos[0]

        agendados.append(item)
        novos += 1
        anexos = f"PDF + XML" if len(arquivos) == 2 else f"{'PDF' if pdf_path else 'XML'}" if arquivos else "sem anexo"
        print(f"  Agendado: {r['apelido']} → {whatsapp} às {envio.strftime('%H:%M')} ({anexos})")

    if novos > 0:
        salvar_agendados(agendados)
        print(f"\n{novos} mensagem(ns) agendada(s) no Forster Lembretes.")
        print("IMPORTANTE: reinicie o Forster Lembretes para que ele carregue os novos agendamentos.")
    else:
        print("Nenhuma mensagem agendada.")


if __name__ == "__main__":
    main()
