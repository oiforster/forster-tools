#!/usr/bin/env python3
"""
emitir_nfs.py — Emissão automática de NFS-e via IPM Fiscal (Igrejinha/RS)

Envia uma NFS-e para cada cliente recorrente configurado em config_emissao.json.

Uso:
    python3 emitir_nfs.py              # emite para todos os clientes
    python3 emitir_nfs.py --dry-run    # mostra o XML sem enviar
    python3 emitir_nfs.py --teste      # envia em modo teste (não gera NF real)
    python3 emitir_nfs.py --cliente "Vanessa"  # emite só para um cliente (busca por nome)
"""

import argparse
import base64
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config_emissao.json"


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def carregar_config():
    if not CONFIG_FILE.exists():
        print(f"Erro: arquivo de configuração não encontrado em {CONFIG_FILE}")
        print("Copie config_emissao.exemplo.json para config_emissao.json e preencha os dados.")
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Montagem do XML
# ---------------------------------------------------------------------------

def formatar_valor(valor_float):
    """Converte float para o formato IPM: vírgula como separador decimal, sem ponto de milhar."""
    # Ex: 2000.0 → "2000,00" | 2696.0 → "2696,00"
    return f"{valor_float:.2f}".replace(".", ",")


def montar_xml(cliente, config, modo_teste=False):
    prestador_cnpj = config["prestador"]["cnpj"]
    prestador_tom  = config["prestador"]["cidade_tom"]
    servico        = config["servico"]

    cpfcnpj = cliente["cpfcnpj"]
    valor   = formatar_valor(cliente["valor"])

    complemento_xml = ""
    if cliente.get("complemento"):
        complemento_xml = f"\n    <complemento>{cliente['complemento']}</complemento>"

    teste_tag = "\n  <nfse_teste>1</nfse_teste>" if modo_teste else ""

    # situacao_tributaria pode ser sobrescrita por cliente (ex: tomador retém ISS)
    situacao = cliente.get("situacao_tributaria", servico["situacao_tributaria"])

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfse>{teste_tag}
  <nf>
    <valor_total>{valor}</valor_total>
  </nf>
  <prestador>
    <cpfcnpj>{prestador_cnpj}</cpfcnpj>
    <cidade>{prestador_tom}</cidade>
  </prestador>
  <tomador>
    <tipo>{cliente['tipo']}</tipo>
    <cpfcnpj>{cpfcnpj}</cpfcnpj>
    <nome_razao_social>{cliente['nome']}</nome_razao_social>
    <logradouro>{cliente['logradouro']}</logradouro>
    <numero_residencia>{cliente['numero']}</numero_residencia>{complemento_xml}
    <bairro>{cliente['bairro']}</bairro>
    <cidade>{cliente['cidade_tom']}</cidade>
    <cep>{cliente['cep']}</cep>
  </tomador>
  <itens>
    <lista>
      <tributa_municipio_prestador>S</tributa_municipio_prestador>
      <codigo_local_prestacao_servico>{prestador_tom}</codigo_local_prestacao_servico>
      <codigo_nbs>{servico['codigo_nbs']}</codigo_nbs>
      <codigo_item_lista_servico>{servico['codigo']}</codigo_item_lista_servico>
      <descritivo>{servico['descricao']}</descritivo>
      <aliquota_item_lista_servico>{servico['aliquota_iss']}</aliquota_item_lista_servico>
      <situacao_tributaria>{situacao}</situacao_tributaria>
      <valor_tributavel>{valor}</valor_tributavel>
    </lista>
  </itens>
</nfse>"""


# ---------------------------------------------------------------------------
# Envio via HTTP (sem dependências externas — usa urllib da biblioteca padrão)
# ---------------------------------------------------------------------------

BOUNDARY = "----ForsterToolsBoundary"


def montar_multipart(xml_bytes):
    """Monta o corpo multipart/form-data manualmente (sem biblioteca externa)."""
    body = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="f1"; filename="nota.xml"\r\n'
        f"Content-Type: text/xml\r\n"
        f"\r\n"
    ).encode("utf-8") + xml_bytes + f"\r\n--{BOUNDARY}--\r\n".encode("utf-8")
    return body


def enviar_nf(xml_str, config):
    url      = config["prestador"]["url_ws"]
    cnpj     = config["prestador"]["cnpj"]
    senha    = config["prestador"]["senha_portal"]

    credencial = base64.b64encode(f"{cnpj}:{senha}".encode()).decode()

    xml_bytes = xml_str.encode("utf-8")
    body      = montar_multipart(xml_bytes)

    req = urllib.request.Request(url, data=body)
    req.add_header("Authorization", f"Basic {credencial}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={BOUNDARY}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return raw.decode("utf-8", errors="replace") if b"\xe7" not in raw else raw.decode("iso-8859-1")
    except urllib.error.HTTPError as e:
        return f"Erro HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}"
    except urllib.error.URLError as e:
        return f"Erro de conexão: {e.reason}"


# ---------------------------------------------------------------------------
# Interpretação do retorno
# ---------------------------------------------------------------------------

def interpretar_retorno(xml_retorno):
    """Extrai número da NF e status do XML de retorno do IPM."""
    if "<numero_nfse>" in xml_retorno:
        inicio = xml_retorno.index("<numero_nfse>") + len("<numero_nfse>")
        fim    = xml_retorno.index("</numero_nfse>")
        numero = xml_retorno[inicio:fim]
        return True, f"NF emitida com sucesso — número {numero}"
    if "<codigo>" in xml_retorno:
        inicio = xml_retorno.index("<codigo>") + len("<codigo>")
        fim    = xml_retorno.index("</codigo>")
        codigo = xml_retorno[inicio:fim]
        if "00001" in codigo or "Sucesso" in codigo:
            return True, f"Sucesso: {codigo}"
        return False, f"Erro do servidor: {codigo}"
    return False, f"Retorno inesperado: {xml_retorno[:300]}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Emissão automática de NFS-e — IPM Fiscal Igrejinha/RS")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o XML sem enviar")
    parser.add_argument("--teste",   action="store_true", help="Envia em modo teste (não gera NF real)")
    parser.add_argument("--cliente", help="Nome parcial do cliente para emitir apenas para ele")
    args = parser.parse_args()

    config   = carregar_config()
    clientes = config["clientes"]

    if args.cliente:
        clientes = [c for c in clientes if args.cliente.lower() in c["nome"].lower()]
        if not clientes:
            print(f"Nenhum cliente encontrado com '{args.cliente}'.")
            sys.exit(1)

    modo = "DRY-RUN" if args.dry_run else ("TESTE" if args.teste else "PRODUÇÃO")
    print(f"\nEmissão de NFS-e — {datetime.now().strftime('%d/%m/%Y %H:%M')} — modo {modo}")
    print(f"Prestador CNPJ: {config['prestador']['cnpj']}")
    print("=" * 60)

    erros = 0
    for cliente in clientes:
        nome  = cliente["nome"]
        valor = cliente["valor"]
        print(f"\n> {nome}")
        print(f"  Valor: R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        xml = montar_xml(cliente, config, modo_teste=args.teste)

        if args.dry_run:
            print("  XML que seria enviado:")
            print(xml)
            continue

        retorno = enviar_nf(xml, config)
        ok, msg = interpretar_retorno(retorno)
        status  = "OK" if ok else "ERRO"
        print(f"  [{status}] {msg}")
        if not ok:
            erros += 1

    print("\n" + "=" * 60)
    if args.dry_run:
        print("Dry-run concluído. Nenhuma NF foi enviada.")
    elif erros == 0:
        print(f"Concluído — {len(clientes)} NF(s) emitida(s) com sucesso.")
    else:
        print(f"Concluído com {erros} erro(s). Verifique acima.")
        sys.exit(1)


if __name__ == "__main__":
    main()
