#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emitir_nfs_ipm.py — Forster
============================
O que faz:
  Emite NFS-e via WebService IPM da Prefeitura de Igrejinha/RS.
  Lê emissor e clientes do config_emissao.json, monta XML no formato
  IPM (NTE-35/2021, sem bloco IBSCBS — Simples Nacional), envia via
  POST multipart/form-data com autenticação HTTP Basic (CNPJ:senha_ipm).
  Reutiliza sessão via cookie PHPSESSID entre requisições. Salva
  retorno em logs/ipm_YYYY-MM-DD_HHmmSS_cliente.xml.

Uso:
  python3 emitir_nfs_ipm.py                          # emite para todos os clientes do emissor padrão
  python3 emitir_nfs_ipm.py --emissor silvana_ltda    # define o emissor
  python3 emitir_nfs_ipm.py --cliente "Vanessa"       # busca por substring no apelido
  python3 emitir_nfs_ipm.py --teste                   # dry-run via tag IPM (valida sem emitir)
  python3 emitir_nfs_ipm.py --todos                   # emite para todos (comportamento padrão)

Campos obrigatórios no emissor (config_emissao.json):
  cnpj, cMunGer, senha_ipm, clientes[]

Campos opcionais no emissor:
  cMunGer_tom        — código TOM do município (fallback para cMunGer se ausente)
  aliquota_iss_ipm   — alíquota ISS (padrão: "2,01")
  situacao_tributaria_ipm — situação tributária (padrão: "0")

Campos obrigatórios por cliente:
  apelido, nome, logradouro, numero, bairro, cMun, cep, valor
  + cnpj (PJ) ou cpf (PF)

Dependências externas:
  Nenhuma (usa apenas stdlib Python 3.9+)

Última atualização: 2026-04-07
"""

import argparse
import base64
import html
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config_emissao.json"
LOGS_DIR    = SCRIPT_DIR / "logs"

URL_WS_IPM     = "https://igrejinha.atende.net/?pg=rest&service=WNERestServiceNFSe"
BOUNDARY       = "----ForsterIPMBoundary"
EMISSOR_PADRAO = "silvana_ltda"

# Defaults IPM para Simples Nacional em Igrejinha
ALIQUOTA_ISS_PADRAO      = "2,01"
SITUACAO_TRIB_PADRAO     = "0"
TRIBUTA_MUNICIPIO_PADRAO = "1"
CODIGO_ITEM_PADRAO       = "130301"


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def carregar_config():
    if not CONFIG_FILE.exists():
        print(f"❌ Config não encontrado: {CONFIG_FILE}")
        print("   Copie config_emissao.exemplo.json → config_emissao.json e preencha.")
        sys.exit(1)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Erro ao ler config_emissao.json: {e}")
        sys.exit(1)


def obter_emissor(config, nome_emissor=None):
    nome = nome_emissor or config.get("emissor_ativo", EMISSOR_PADRAO)
    if nome not in config.get("emissores", {}):
        disponiveis = list(config.get("emissores", {}).keys())
        print(f"❌ Emissor '{nome}' não encontrado. Disponíveis: {disponiveis}")
        sys.exit(1)
    return config["emissores"][nome], nome


def obter_senha_ipm(emissor):
    """Retorna a senha IPM do emissor; exige campo 'senha_ipm' no config."""
    senha = emissor.get("senha_ipm")
    if not senha:
        print("❌ Campo 'senha_ipm' ausente no emissor. Adicione ao config_emissao.json.")
        sys.exit(1)
    return senha


# ---------------------------------------------------------------------------
# Montagem do XML IPM (NTE-35/2021)
# ---------------------------------------------------------------------------

def escapar_xml(texto):
    """Escapa caracteres especiais XML em campos de texto livre (&, <, >, etc.)."""
    return html.escape(str(texto), quote=False)


def formatar_valor(valor_float):
    """Converte float para o formato IPM: vírgula decimal, sem ponto de milhar."""
    return f"{valor_float:.2f}".replace(".", ",")


def derivar_tipo_tomador(cliente):
    """Retorna 'J' para pessoa jurídica (CNPJ) ou 'F' para física (CPF)."""
    return "J" if cliente.get("cnpj") else "F"


def derivar_cpfcnpj_tomador(cliente):
    """Retorna o documento do tomador sem formatação."""
    return cliente.get("cnpj") or cliente.get("cpf", "")


def montar_xml_ipm(cliente, emissor, config, modo_teste=False):
    """Monta o XML da NFS-e no formato IPM (NTE-35/2021, sem bloco IBSCBS)."""
    servico = config.get("servico", {})

    prestador_cnpj = emissor["cnpj"]
    # Usa código TOM quando disponível, com fallback para IBGE
    prestador_tom  = emissor.get("cMunGer_tom") or emissor["cMunGer"]
    codigo_item    = servico.get("cTribNac", CODIGO_ITEM_PADRAO)
    descricao      = servico.get("xDescServ", "Prestação de serviços")
    aliquota       = emissor.get("aliquota_iss_ipm", ALIQUOTA_ISS_PADRAO)
    situacao_trib  = emissor.get("situacao_tributaria_ipm", SITUACAO_TRIB_PADRAO)

    tipo_tom   = derivar_tipo_tomador(cliente)
    cpfcnpj    = derivar_cpfcnpj_tomador(cliente)
    valor      = formatar_valor(cliente["valor"])
    cidade_tom = cliente["cMun"]

    complemento_xml = ""
    if cliente.get("complemento"):
        comp = cliente["complemento"]
        complemento_xml = f"\n    <complemento>{comp}</complemento>"

    teste_tag = "\n  <nfse_teste>1</nfse_teste>" if modo_teste else ""

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
    <tipo>{tipo_tom}</tipo>
    <cpfcnpj>{cpfcnpj}</cpfcnpj>
    <nome_razao_social>{escapar_xml(cliente['nome'])}</nome_razao_social>
    <logradouro>{escapar_xml(cliente['logradouro'])}</logradouro>
    <numero_residencia>{escapar_xml(cliente['numero'])}</numero_residencia>{complemento_xml}
    <bairro>{escapar_xml(cliente['bairro'])}</bairro>
    <cidade>{cidade_tom}</cidade>
    <cep>{cliente['cep']}</cep>
  </tomador>
  <itens>
    <lista>
      <tributa_municipio_prestador>{TRIBUTA_MUNICIPIO_PADRAO}</tributa_municipio_prestador>
      <codigo_local_prestacao_servico>{prestador_tom}</codigo_local_prestacao_servico>
      <codigo_item_lista_servico>{codigo_item}</codigo_item_lista_servico>
      <descritivo>{escapar_xml(descricao)}</descritivo>
      <aliquota_item_lista_servico>{aliquota}</aliquota_item_lista_servico>
      <situacao_tributaria>{situacao_trib}</situacao_tributaria>
      <valor_tributavel>{valor}</valor_tributavel>
    </lista>
  </itens>
</nfse>"""


# ---------------------------------------------------------------------------
# HTTP — sessão com reutilização de cookie
# ---------------------------------------------------------------------------

def criar_sessao_http():
    """Cria opener urllib com gerenciamento automático de cookies (PHPSESSID)."""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def montar_multipart(xml_bytes):
    """Monta corpo multipart/form-data com o XML da NFS-e."""
    corpo = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="f1"; filename="nota.xml"\r\n'
        f"Content-Type: text/xml\r\n"
        f"\r\n"
    ).encode("utf-8") + xml_bytes + f"\r\n--{BOUNDARY}--\r\n".encode("utf-8")
    return corpo


def obter_credencial_basic(emissor):
    """Monta header Authorization: Basic base64(usuario:senha_ipm).
    Prioridade: usuario_ipm explícito > CNPJ (im não é aceito pelo IPM Igrejinha)."""
    usuario = emissor.get("usuario_ipm") or emissor["cnpj"]
    senha   = obter_senha_ipm(emissor)
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


def enviar_nfse_ipm(xml_str, emissor, opener):
    """Envia XML ao WebService IPM via POST multipart/form-data, reutilizando sessão."""
    credencial = obter_credencial_basic(emissor)
    xml_bytes  = xml_str.encode("utf-8")
    corpo      = montar_multipart(xml_bytes)

    url_ws = emissor.get("url_ws_ipm", URL_WS_IPM)

    req = urllib.request.Request(url_ws, data=corpo)
    req.add_header("Authorization", credencial)
    req.add_header("Content-Type", f"multipart/form-data; boundary={BOUNDARY}")

    try:
        with opener.open(req, timeout=30) as resp:
            raw = resp.read()
            # IPM pode responder em ISO-8859-1
            return raw.decode("utf-8", errors="replace") if b"\xe7" not in raw else raw.decode("iso-8859-1")
    except urllib.error.HTTPError as e:
        corpo_erro = e.read().decode("utf-8", errors="replace")
        return f"<erro><http>{e.code}</http><detalhe>{corpo_erro[:500]}</detalhe></erro>"
    except urllib.error.URLError as e:
        return f"<erro><conexao>{e.reason}</conexao></erro>"
    except Exception as e:
        return f"<erro><inesperado>{e}</inesperado></erro>"


# ---------------------------------------------------------------------------
# Interpretação do retorno XML
# ---------------------------------------------------------------------------

def extrair_tag(xml_str, tag):
    """Extrai conteúdo de uma tag simples no XML de retorno."""
    abertura  = f"<{tag}>"
    fechamento = f"</{tag}>"
    if abertura in xml_str and fechamento in xml_str:
        inicio = xml_str.index(abertura) + len(abertura)
        fim    = xml_str.index(fechamento)
        return xml_str[inicio:fim].strip()
    return ""


def interpretar_retorno_ipm(xml_retorno):
    """
    Interpreta o XML de retorno do IPM.
    Retorna (sucesso: bool, mensagem: str, dados: dict).
    """
    dados = {
        "numero_nfse":       extrair_tag(xml_retorno, "numero_nfse"),
        "cod_verificador":   extrair_tag(xml_retorno, "cod_verificador_autenticidade"),
        "link":              extrair_tag(xml_retorno, "link_nfse"),
        "codigo":            extrair_tag(xml_retorno, "codigo"),
        "mensagem_servidor": extrair_tag(xml_retorno, "mensagem"),
    }

    # Sucesso: retorno contém número da NFS-e
    if dados["numero_nfse"]:
        msg = f"NFS-e emitida — nº {dados['numero_nfse']}"
        if dados["cod_verificador"]:
            msg += f", cod. verificador: {dados['cod_verificador']}"
        return True, msg, dados

    # Verificar código de sucesso IPM — só "00001" ou mensagem explícita de sucesso
    codigo = dados["codigo"]
    if codigo and (codigo.startswith("00001") or "válida para emiss" in codigo.lower() or "sucesso" in codigo.lower()):
        return True, f"Sucesso: {codigo}", dados

    # Erro
    motivo = dados["mensagem_servidor"] or dados["codigo"] or xml_retorno[:300]
    return False, f"Erro IPM: {motivo}", dados


# ---------------------------------------------------------------------------
# Persistência — logs
# ---------------------------------------------------------------------------

def salvar_retorno_logs(xml_retorno, apelido_cliente, modo_teste):
    """Salva XML de retorno em logs/ com nome datado."""
    LOGS_DIR.mkdir(exist_ok=True)
    sufixo  = "_teste" if modo_teste else ""
    data    = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slug    = apelido_cliente.lower().replace(" ", "_")
    caminho = LOGS_DIR / f"ipm_{data}_{slug}{sufixo}.xml"
    try:
        caminho.write_text(xml_retorno, encoding="utf-8")
        return caminho
    except OSError as e:
        print(f"  ⚠️  Não foi possível salvar log: {e}")
        return None


# ---------------------------------------------------------------------------
# Exibição pós-emissão
# ---------------------------------------------------------------------------

def exibir_resultado_emissao(dados):
    """Imprime número, link e cod_verificador do retorno."""
    if dados.get("numero_nfse"):
        print(f"  Nº NFS-e:         {dados['numero_nfse']}")
    if dados.get("cod_verificador"):
        print(f"  Cod. verificador: {dados['cod_verificador']}")
    if dados.get("link"):
        print(f"  Link:             {dados['link']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Emissão automática de NFS-e — WebService IPM Igrejinha/RS"
    )
    parser.add_argument("--emissor", default=EMISSOR_PADRAO,
                        help="Nome do emissor no config (padrão: silvana_ltda)")
    parser.add_argument("--cliente",
                        help="Substring do apelido do cliente")
    parser.add_argument("--teste",   action="store_true",
                        help="Modo teste IPM — valida sem emitir (insere <nfse_teste>1</nfse_teste>)")
    parser.add_argument("--todos",   action="store_true",
                        help="Emite para todos os clientes (comportamento padrão)")
    args = parser.parse_args()

    config           = carregar_config()
    emissor, nome_em = obter_emissor(config, args.emissor)
    clientes         = emissor.get("clientes", [])

    if not clientes:
        print(f"❌ Nenhum cliente configurado para o emissor '{nome_em}'.")
        sys.exit(1)

    if args.cliente:
        busca    = args.cliente.lower()
        clientes = [c for c in clientes
                    if busca in c.get("apelido", "").lower()
                    or busca in c.get("nome", "").lower()]
        if not clientes:
            print(f"❌ Nenhum cliente encontrado com '{args.cliente}'.")
            sys.exit(1)

    modo = "TESTE (sem emissão real)" if args.teste else "PRODUÇÃO"
    print(f"\nEmissão NFS-e IPM — {datetime.now().strftime('%d/%m/%Y %H:%M')} — {modo}")
    print(f"Emissor: {nome_em} (CNPJ {emissor['cnpj']})")
    print(f"Clientes: {len(clientes)}")
    print("=" * 65)

    opener = criar_sessao_http()
    erros  = 0

    for cliente in clientes:
        apelido = cliente.get("apelido", cliente["nome"][:30])
        valor   = cliente["valor"]
        print(f"\n> {apelido}")
        print(f"  Valor: R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        xml = montar_xml_ipm(cliente, emissor, config, modo_teste=args.teste)

        print("  Enviando para IPM Igrejinha...")
        retorno = enviar_nfse_ipm(xml, emissor, opener)

        ok, msg, dados = interpretar_retorno_ipm(retorno)
        status = "OK" if ok else "ERRO"
        print(f"  [{status}] {msg}")

        if ok:
            exibir_resultado_emissao(dados)

        caminho_log = salvar_retorno_logs(retorno, apelido, args.teste)
        if caminho_log:
            print(f"  Log salvo: {caminho_log.name}")

        if not ok:
            erros += 1

    print("\n" + "=" * 65)
    if erros == 0:
        sufixo = " (modo teste — nenhuma NF real emitida)" if args.teste else ""
        print(f"Concluído — {len(clientes)} NFS-e(s) processada(s) com sucesso.{sufixo}")
    else:
        print(f"Concluído com {erros} erro(s). Verifique o retorno acima e os logs/.")
        sys.exit(1)


if __name__ == "__main__":
    main()
