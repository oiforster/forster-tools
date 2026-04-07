#!/usr/bin/env python3
"""
emitir_nfs_nacional.py — Emissão automática de NFS-e via Portal Nacional (sefin.nfse.gov.br)

Envia DPS (Declaração de Prestação de Serviço) para gerar NFS-e no padrão nacional.
Suporta múltiplos emissores (MEI e Simples Nacional).

Uso:
    python3 emitir_nfs_nacional.py                          # emite para todos os clientes do emissor ativo
    python3 emitir_nfs_nacional.py --dry-run                # mostra o XML sem enviar
    python3 emitir_nfs_nacional.py --cliente "Vanessa"      # emite só para um cliente
    python3 emitir_nfs_nacional.py --emissor silvana_simples # usa outro emissor
    python3 emitir_nfs_nacional.py --homologacao            # força ambiente de homologação
    python3 emitir_nfs_nacional.py --competencia 2026-03    # define mês de competência (padrão: mês atual)
"""

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import ssl
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from lxml import etree
except ImportError:
    print("Erro: lxml não instalado. Rode: pip3 install lxml")
    sys.exit(1)

try:
    from signxml import XMLSigner, methods
except ImportError:
    XMLSigner = None  # assinatura desabilitada — dry-run ainda funciona

try:
    from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
except ImportError:
    pkcs12 = None  # extração de certificado desabilitada


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

CONFIG_FILE = Path(__file__).parent / "config_emissao.json"

URLS = {
    "producao":    "https://sefin.nfse.gov.br/SefinNacional/nfse",
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional/nfse",
}

URLS_CONSULTA = {
    "producao":    "https://sefin.nfse.gov.br/SefinNacional/nfse/",
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional/nfse/",
}

URLS_DANFSE = {
    "producao":    "https://sefin.nfse.gov.br/SefinNacional/danfse/",
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional/danfse/",
}

NS = "http://www.sped.fazenda.gov.br/nfse"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"

FUSO_BR = timezone(timedelta(hours=-3))

# Caminhos de armazenamento
FINANCEIRO_BASE = Path(os.path.expanduser(
    "~/Library/CloudStorage/SynologyDrive-Agencia/_Financeiro"
))
CONTROLE_NFS = FINANCEIRO_BASE / "Controle_NFS_Samuel.md"
NOTAS_BASE = FINANCEIRO_BASE / "Notas_Fiscais"


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def carregar_config():
    if not CONFIG_FILE.exists():
        print(f"Erro: config não encontrado em {CONFIG_FILE}")
        print("Copie config_emissao.exemplo.json → config_emissao.json e preencha.")
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def obter_emissor(config, nome_emissor=None):
    nome = nome_emissor or config.get("emissor_ativo")
    if nome not in config["emissores"]:
        print(f"Erro: emissor '{nome}' não encontrado. Disponíveis: {list(config['emissores'].keys())}")
        sys.exit(1)
    return config["emissores"][nome], nome


# ---------------------------------------------------------------------------
# Certificado digital (.pfx → .pem + .key)
# ---------------------------------------------------------------------------

def carregar_certificado(emissor):
    """Carrega o certificado .pfx e retorna (cert_pem_path, key_pem_path)."""
    cert_cfg = emissor["certificado"]
    pfx_path = Path(__file__).parent / cert_cfg["pfx"]

    if not pfx_path.exists():
        return None, None

    # Verifica se já extraiu .pem e .key
    pem_path = pfx_path.with_suffix(".pem")
    key_path = pfx_path.with_suffix(".key")

    if pem_path.exists() and key_path.exists():
        return str(pem_path), str(key_path)

    if pkcs12 is None:
        print("Erro: cryptography não instalado. Rode: pip3 install cryptography")
        sys.exit(1)

    senha = cert_cfg.get("senha", "").encode()
    with open(pfx_path, "rb") as f:
        private_key, certificate, chain = pkcs12.load_key_and_certificates(f.read(), senha or None)

    # Salva .key
    key_bytes = private_key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
    key_path.write_bytes(key_bytes)

    # Salva .pem (cert + chain)
    from cryptography.hazmat.primitives.serialization import Encoding as CertEncoding
    pem_parts = [certificate.public_bytes(CertEncoding.PEM)]
    if chain:
        for cert in chain:
            pem_parts.append(cert.public_bytes(CertEncoding.PEM))
    pem_path.write_bytes(b"".join(pem_parts))

    print(f"  Certificado extraído: {pem_path.name} + {key_path.name}")
    return str(pem_path), str(key_path)


# ---------------------------------------------------------------------------
# Montagem do XML DPS
# ---------------------------------------------------------------------------

def calcular_cdv(chave):
    """Módulo 11 — retorna o dígito verificador da chave de acesso DPS (mesmo algoritmo NFe)."""
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(d) * pesos[i % len(pesos)] for i, d in enumerate(reversed(chave)))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def montar_id_dps(emissor, serie, ndps):
    """
    Monta o Id da DPS conforme padrão nacional (regex: DPS[0-9]{42}):
    DPS + cMunEmi(7) + tpInscFed(1) + inscFed(14) + serie(5) + nDPS(15) = 45 chars
    tpInscFed: 1=CPF, 2=CNPJ (padrão NFS-e Nacional, diferente da NFe)
    Não há dígito verificador no Id da DPS (cDV existe apenas na chave da NFS-e).
    """
    cmun = emissor["cMunGer"]          # 7 dígitos
    tipo = "2"                         # 2 = CNPJ (padrão NFS-e Nacional)
    cnpj = emissor["cnpj"].zfill(14)   # 14 dígitos
    serie_pad = serie.zfill(5)[:5]     # 5 dígitos numéricos
    ndps_pad = str(ndps).zfill(15)     # 15 dígitos
    return f"DPS{cmun}{tipo}{cnpj}{serie_pad}{ndps_pad}"  # 3 + 42 = 45 chars


def sub(parent, tag, texto=None, attribs=None):
    """Helper: cria subelemento com namespace."""
    el = etree.SubElement(parent, f"{{{NS}}}{tag}", **(attribs or {}))
    if texto is not None:
        el.text = str(texto)
    return el


def montar_dps_xml(cliente, emissor, config, ndps, ambiente="homologacao", competencia=None):
    """Monta o XML da DPS no padrão nacional."""
    servico = config["servico"]
    controle = emissor.get("controle_dps") or config["controle_dps"]
    serie = controle["serie"]

    agora = datetime.now(FUSO_BR)
    tp_amb = "2" if ambiente == "homologacao" else "1"
    dcompet = competencia or agora.strftime("%Y-%m-01")
    id_dps = montar_id_dps(emissor, serie, ndps)

    # Raiz: DPS
    nsmap = {None: NS}
    dps = etree.Element(f"{{{NS}}}DPS", nsmap=nsmap)
    dps.set("versao", "1.00")

    # infDPS
    inf = sub(dps, "infDPS", attribs={"Id": id_dps})
    sub(inf, "tpAmb", tp_amb)
    sub(inf, "dhEmi", agora.strftime("%Y-%m-%dT%H:%M:%S") + "-03:00")
    sub(inf, "verAplic", "ForsterTools1.0")
    sub(inf, "serie", serie)
    sub(inf, "nDPS", str(ndps))
    sub(inf, "dCompet", dcompet)
    sub(inf, "tpEmit", "1")  # Prestador
    sub(inf, "cLocEmi", emissor["cMunGer"])

    # prest (prestador)
    prest = sub(inf, "prest")
    sub(prest, "CNPJ", emissor["cnpj"])
    if emissor.get("im"):
        sub(prest, "IM", emissor["im"])

    # regTrib
    reg = sub(prest, "regTrib")
    if emissor["regime"] == "MEI":
        sub(reg, "opSimpNac", "2")   # 2 = MEI
    else:
        sub(reg, "opSimpNac", "3")   # 3 = ME/EPP (Simples Nacional)
    sub(reg, "regEspTrib", "0")      # 0 = Nenhum

    # toma (tomador)
    toma = sub(inf, "toma")
    if cliente.get("cnpj"):
        sub(toma, "CNPJ", cliente["cnpj"])
    elif cliente.get("cpf"):
        sub(toma, "CPF", cliente["cpf"])
    sub(toma, "xNome", cliente["nome"])

    # endereço do tomador
    end = sub(toma, "end")
    end_nac = sub(end, "endNac")
    sub(end_nac, "cMun", cliente["cMun"])
    sub(end_nac, "CEP", cliente["cep"])
    sub(end, "xLgr", cliente["logradouro"])
    sub(end, "nro", cliente["numero"])
    if cliente.get("complemento"):
        sub(end, "xCpl", cliente["complemento"])
    sub(end, "xBairro", cliente["bairro"])

    # serv (serviço)
    serv = sub(inf, "serv")
    loc = sub(serv, "locPrest")
    # Local de prestação = município do tomador (onde o serviço é entregue)
    sub(loc, "cLocPrestacao", cliente["cMun"])

    cserv = sub(serv, "cServ")
    sub(cserv, "cTribNac", servico["cTribNac"])
    sub(cserv, "xDescServ", servico["xDescServ"])
    sub(cserv, "cNBS", servico["CNBS"])

    # valores
    valores = sub(inf, "valores")
    vsp = sub(valores, "vServPrest")
    sub(vsp, "vServ", f"{cliente['valor']:.2f}")

    # trib (tributos)
    trib = sub(valores, "trib")

    # tribMun (ISSQN)
    trib_mun = sub(trib, "tribMun")
    sub(trib_mun, "tribISSQN", "1")       # 1 = Operação tributável
    sub(trib_mun, "tpRetISSQN", "1")      # 1 = Não retido

    # totTrib (totais aproximados — MEI pode informar indTotTrib=0 para não informar)
    tot = sub(trib, "totTrib")
    sub(tot, "indTotTrib", "0")  # 0 = Não informa valores de tributos

    return dps


def xml_para_string(dps_element):
    """Serializa o XML com declaração e encoding UTF-8."""
    return etree.tostring(
        dps_element,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )


# ---------------------------------------------------------------------------
# Assinatura digital XML
# ---------------------------------------------------------------------------

def assinar_xml(xml_bytes, cert_pem, key_pem):
    """
    Assina o XML da DPS com certificado digital A1.
    Implementação manual para gerar Signature sem prefixo 'ds:'
    (exigência do Portal Nacional NFS-e).

    Estratégia: montar o Signature como árvore lxml dentro do DPS,
    canonicalizar o SignedInfo no contexto real do documento (para
    capturar exatamente o que o servidor vai recomputar), e assinar
    essa canonical form.
    """
    if pkcs12 is None:
        print("  AVISO: cryptography não instalado — XML não assinado")
        return xml_bytes

    from cryptography.hazmat.primitives import hashes as crypto_hashes
    from cryptography.hazmat.primitives.asymmetric import padding as crypto_padding
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509 import load_pem_x509_certificates

    C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
    SIG_ALG = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
    DIGEST_ALG = "http://www.w3.org/2001/04/xmlenc#sha256"
    ENVELOPE_ALG = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"

    # Lê chave e certificados
    with open(key_pem, "rb") as f:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        private_key = load_pem_private_key(f.read(), password=None)
    with open(cert_pem, "rb") as f:
        certs = load_pem_x509_certificates(f.read())

    root = etree.fromstring(xml_bytes)
    inf_dps = root.find(f"{{{NS}}}infDPS")
    ref_uri = f"#{inf_dps.get('Id')}"

    # --- 1. Digest do infDPS (transform: enveloped-sig + c14n) ---
    # Serialize standalone → reparse → c14n para evitar xmlns="" espúrios.
    # lxml produz undeclarations quando faz c14n de subtree com ancestor
    # de namespace diferente. Ao reparsear sem o DPS ancestor, o namespace
    # fica corretamente declarado no próprio infDPS.
    inf_standalone = etree.tostring(inf_dps)
    inf_reparsed = etree.fromstring(inf_standalone)
    inf_c14n = etree.tostring(inf_reparsed, method="c14n")
    digest_bytes = hashlib.sha256(inf_c14n).digest()
    digest_b64 = base64.b64encode(digest_bytes).decode("ascii")

    # --- 2. Monta Signature como árvore lxml dentro do DPS ---
    # Os elementos são criados NO namespace dsig com nsmap sem prefixo.
    ds_nsmap = {None: NS_DS}

    sig_el = etree.SubElement(root, f"{{{NS_DS}}}Signature", nsmap=ds_nsmap)

    si_el = etree.SubElement(sig_el, f"{{{NS_DS}}}SignedInfo")
    etree.SubElement(si_el, f"{{{NS_DS}}}CanonicalizationMethod",
                     Algorithm=C14N)
    etree.SubElement(si_el, f"{{{NS_DS}}}SignatureMethod",
                     Algorithm=SIG_ALG)

    ref_el = etree.SubElement(si_el, f"{{{NS_DS}}}Reference", URI=ref_uri)
    transforms_el = etree.SubElement(ref_el, f"{{{NS_DS}}}Transforms")
    etree.SubElement(transforms_el, f"{{{NS_DS}}}Transform",
                     Algorithm=ENVELOPE_ALG)
    etree.SubElement(transforms_el, f"{{{NS_DS}}}Transform",
                     Algorithm=C14N)
    etree.SubElement(ref_el, f"{{{NS_DS}}}DigestMethod",
                     Algorithm=DIGEST_ALG)
    dv_el = etree.SubElement(ref_el, f"{{{NS_DS}}}DigestValue")
    dv_el.text = digest_b64

    # Placeholder para SignatureValue (será preenchido depois)
    sv_el = etree.SubElement(sig_el, f"{{{NS_DS}}}SignatureValue")

    # --- 3. Canonicaliza SignedInfo como subtree standalone ---
    # lxml produz xmlns="" espúrios ao c14n de subtree com ancestor de outro namespace.
    # Solução: serializar → reparsear → c14n (sem contexto do DPS ancestor).
    si_standalone = etree.tostring(si_el)
    si_reparsed = etree.fromstring(si_standalone)
    si_c14n = etree.tostring(si_reparsed, method="c14n")

    # --- 4. Assina o SignedInfo canônico ---
    signature_bytes = private_key.sign(
        si_c14n,
        crypto_padding.PKCS1v15(),
        crypto_hashes.SHA256(),
    )
    sv_el.text = base64.b64encode(signature_bytes).decode("ascii")

    # --- 5. Adiciona KeyInfo com certificado end-entity ---
    ki_el = etree.SubElement(sig_el, f"{{{NS_DS}}}KeyInfo")
    x509_data = etree.SubElement(ki_el, f"{{{NS_DS}}}X509Data")
    x509_cert = etree.SubElement(x509_data, f"{{{NS_DS}}}X509Certificate")
    cert_der = certs[0].public_bytes(Encoding.DER)
    x509_cert.text = base64.b64encode(cert_der).decode("ascii")

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


# ---------------------------------------------------------------------------
# Compactação e envio
# ---------------------------------------------------------------------------

def comprimir_e_codificar(xml_bytes):
    """GZip + Base64 do XML assinado."""
    compressed = gzip.compress(xml_bytes)
    return base64.b64encode(compressed).decode("ascii")


def enviar_dps(xml_b64, cert_pem, key_pem, ambiente="homologacao"):
    """Envia a DPS via POST JSON com mTLS."""
    url = URLS[ambiente]

    payload = json.dumps({"dpsXmlGZipB64": xml_b64}).encode("utf-8")

    # Configura SSL com certificado do cliente (mTLS)
    ctx = ssl.create_default_context()
    ctx.load_cert_chain(certfile=cert_pem, keyfile=key_pem)

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"erro": True, "codigo": e.code, "mensagem": body, "body_completo": body}
    except urllib.error.URLError as e:
        return {"erro": True, "codigo": 0, "mensagem": str(e.reason)}


# ---------------------------------------------------------------------------
# Interpretação do retorno
# ---------------------------------------------------------------------------

def interpretar_retorno(resposta):
    """Interpreta a resposta JSON do Portal Nacional."""
    if isinstance(resposta, dict) and resposta.get("erro"):
        return False, f"Erro HTTP {resposta['codigo']}: {resposta['mensagem']}"

    # Resposta bem-sucedida contém chave de acesso da NFS-e
    if isinstance(resposta, dict):
        if "chNFSe" in resposta or "chaveAcesso" in resposta:
            chave = resposta.get("chNFSe") or resposta.get("chaveAcesso", "")
            nfse_num = resposta.get("nNFSe", resposta.get("numero", "?"))
            return True, f"NFS-e emitida — nº {nfse_num}, chave: {chave}"
        if "mensagem" in resposta:
            return False, f"Rejeição: {resposta['mensagem'][:200]}"

    return False, f"Retorno inesperado: {str(resposta)[:300]}"


# ---------------------------------------------------------------------------
# Controle de numeração
# ---------------------------------------------------------------------------

def proximo_ndps(config, emissor=None):
    """Retorna o próximo nDPS e incrementa no config (ou no emissor, se tiver controle_dps próprio)."""
    controle = (emissor.get("controle_dps") if emissor else None) or config["controle_dps"]
    n = controle["proximo_nDPS"]
    controle["proximo_nDPS"] = n + 1
    return n


def salvar_config(config):
    """Persiste o config atualizado (para incrementar nDPS)."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Pós-emissão: download, arquivamento e controle
# ---------------------------------------------------------------------------

def baixar_nfse(chave_acesso, cert_pem, key_pem, ambiente="producao"):
    """GET /nfse/{chaveAcesso} → retorna dict com nfseXmlGZipB64 e metadados."""
    url = URLS_CONSULTA[ambiente] + chave_acesso

    ctx = ssl.create_default_context()
    ctx.load_cert_chain(certfile=cert_pem, keyfile=key_pem)

    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"erro": True, "codigo": e.code, "mensagem": body}
    except urllib.error.URLError as e:
        return {"erro": True, "codigo": 0, "mensagem": str(e.reason)}


def baixar_danfse_pdf(chave_acesso, cert_pem, key_pem, ambiente="producao"):
    """GET /danfse/{chaveAcesso} → retorna bytes do PDF da DANFSE."""
    url = URLS_DANFSE[ambiente] + chave_acesso

    ctx = ssl.create_default_context()
    ctx.load_cert_chain(certfile=cert_pem, keyfile=key_pem)

    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/pdf")

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()
            if "pdf" in content_type or data[:5] == b"%PDF-":
                return data
            # Pode retornar JSON com erro
            try:
                err = json.loads(data.decode("utf-8"))
                return {"erro": True, "mensagem": str(err)}
            except (json.JSONDecodeError, UnicodeDecodeError):
                return data  # assume PDF mesmo sem content-type correto
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"erro": True, "codigo": e.code, "mensagem": body}
    except urllib.error.URLError as e:
        return {"erro": True, "codigo": 0, "mensagem": str(e.reason)}


def extrair_xml_nfse(nfse_data):
    """Decodifica nfseXmlGZipB64 → XML string."""
    b64 = nfse_data.get("nfseXmlGZipB64", "")
    if not b64:
        return None
    xml_bytes = gzip.decompress(base64.b64decode(b64))
    return xml_bytes


def extrair_dados_nfse(xml_bytes):
    """Extrai nNFSe e data de emissão do XML da NFS-e."""
    root = etree.fromstring(xml_bytes)
    ns = {"n": NS}
    n_nfse = root.findtext(".//n:infNFSe/n:nNFSe", namespaces=ns)
    if n_nfse is None:
        n_nfse = root.findtext(".//{%s}nNFSe" % NS)
    dh_emi = root.findtext(".//{%s}dhEmi" % NS) or ""
    return n_nfse, dh_emi


def salvar_nfse_xml(xml_bytes, chave_acesso, emissor, competencia, nome_tomador):
    """Salva XML na estrutura _Financeiro/Notas_Fiscais/YYYY/Emissor/YYYY-MM - Tomador/chave.xml"""
    ano = competencia[:4]
    mes_comp = competencia[:7]
    cnpj_fmt = emissor["cnpj"]
    emissor_dir = f"{emissor['nome']} - CNPJ {cnpj_fmt}"

    pasta_nf = NOTAS_BASE / ano / emissor_dir / f"{mes_comp} - {nome_tomador}"
    pasta_nf.mkdir(parents=True, exist_ok=True)

    xml_path = pasta_nf / f"{chave_acesso}.xml"
    xml_path.write_bytes(xml_bytes)
    return xml_path


def formatar_cpf_cnpj(doc):
    """Formata CPF (XXX.XXX.XXX-XX) ou CNPJ (XX.XXX.XXX/XXXX-XX) para exibição."""
    doc = re.sub(r"\D", "", doc)
    if len(doc) == 11:
        return f"{doc[:3]}.{doc[3:6]}.{doc[6:9]}-{doc[9:]}"
    elif len(doc) == 14:
        return f"{doc[:2]}.{doc[2:5]}.{doc[5:8]}/{doc[8:12]}-{doc[12:]}"
    return doc


def atualizar_controle_nfs(n_nfse, data_emissao, cpf_cnpj_tomador, nome_tomador, valor, obs=""):
    """Adiciona linha na tabela do ano corrente em Controle_NFS_Samuel.md"""
    if not CONTROLE_NFS.exists():
        print(f"  AVISO: Controle de NFs não encontrado em {CONTROLE_NFS}")
        return False

    conteudo = CONTROLE_NFS.read_text(encoding="utf-8")
    data_fmt = data_emissao if "/" in data_emissao else datetime.now(FUSO_BR).strftime("%d/%m/%Y")
    doc_fmt = formatar_cpf_cnpj(cpf_cnpj_tomador)
    valor_fmt = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    nova_linha = f"| {n_nfse} | {data_fmt} | {doc_fmt} | {nome_tomador} | {valor_fmt} | {obs} |"

    ano = datetime.now(FUSO_BR).strftime("%Y")
    marcador_total = f"**Total {ano}:**"

    if marcador_total in conteudo:
        linhas = conteudo.split("\n")
        inserido = False
        for i, linha in enumerate(linhas):
            if marcador_total in linha:
                linhas.insert(i, nova_linha)
                inserido = True
                total_ano = _calcular_total_ano(linhas, ano)
                canceladas = _contar_canceladas(linhas, ano)
                total_str = f"R$ {total_ano:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                nota_cancel = " *(NF cancelada — não entra no total)*" if canceladas > 0 else ""
                linhas[i + 1] = f"**Total {ano}:** {total_str}{nota_cancel}"
                break

        if inserido:
            CONTROLE_NFS.write_text("\n".join(linhas), encoding="utf-8")
            return True

    print(f"  AVISO: Seção do ano {ano} não encontrada no controle de NFs.")
    return False


def _calcular_total_ano(linhas, ano):
    """Calcula total de NFs de um ano no controle, ignorando canceladas."""
    na_secao = False
    total = 0.0
    for linha in linhas:
        if f"## {ano}" in linha:
            na_secao = True
            continue
        if na_secao and linha.startswith("## "):
            break
        if na_secao and linha.startswith("|") and "Nº NFS-e" not in linha and "---" not in linha:
            partes = [p.strip() for p in linha.split("|")]
            if len(partes) >= 7:
                obs_col = partes[6] if len(partes) > 6 else ""
                if "cancelada" in obs_col.lower():
                    continue
                val_str = partes[5].replace("R$", "").replace(".", "").replace(",", ".").strip()
                try:
                    total += float(val_str)
                except ValueError:
                    pass
    return total


def _contar_canceladas(linhas, ano):
    """Conta NFs canceladas na seção do ano."""
    na_secao = False
    count = 0
    for linha in linhas:
        if f"## {ano}" in linha:
            na_secao = True
            continue
        if na_secao and linha.startswith("## "):
            break
        if na_secao and "cancelada" in linha.lower() and linha.startswith("|"):
            count += 1
    return count


def processar_pos_emissao(resposta, cliente, emissor, config, competencia, cert_pem, key_pem, ambiente):
    """Fluxo pós-emissão: baixa XML, salva arquivo, atualiza controle. Retorna (chave, n_nfse, xml_path) ou None."""
    chave = resposta.get("chNFSe") or resposta.get("chaveAcesso", "")
    if not chave:
        print("  AVISO: Chave de acesso não encontrada na resposta. Pós-emissão ignorada.")
        return None

    # 1. Baixa NFS-e completa via GET
    print("  Baixando NFS-e...")
    nfse_data = baixar_nfse(chave, cert_pem, key_pem, ambiente)
    if isinstance(nfse_data, dict) and nfse_data.get("erro"):
        print(f"  AVISO: Erro ao baixar NFS-e: {nfse_data.get('mensagem', '')[:200]}")
        return None

    # 2. Decodifica XML
    xml_bytes = extrair_xml_nfse(nfse_data)
    if not xml_bytes:
        print("  AVISO: XML da NFS-e não encontrado na resposta.")
        return None

    # 3. Extrai dados
    n_nfse, dh_emi = extrair_dados_nfse(xml_bytes)
    data_emissao = datetime.now(FUSO_BR).strftime("%d/%m/%Y")
    if dh_emi:
        try:
            dt = datetime.fromisoformat(dh_emi.replace("Z", "+00:00"))
            data_emissao = dt.astimezone(FUSO_BR).strftime("%d/%m/%Y")
        except ValueError:
            pass

    # 4. Salva XML
    nome_tomador = cliente["nome"]
    xml_path = salvar_nfse_xml(xml_bytes, chave, emissor, competencia, nome_tomador)
    print(f"  XML salvo: {xml_path}")

    # 5. Gera PDF local via Node.js (substitui download /danfse que retorna 501)
    import subprocess
    pdf_path = None
    print("  Gerando PDF local...")
    try:
        resultado = subprocess.run(
            ["/opt/homebrew/bin/node", "gerar_pdf_nfse.js", str(xml_path)],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent),
        )
        if resultado.returncode == 0:
            pdf_path = Path(resultado.stdout.strip())
            print(f"  PDF gerado: {pdf_path}")
        else:
            print(f"  AVISO: Falha ao gerar PDF: {resultado.stderr[:200]}")
    except Exception as e:
        print(f"  AVISO: Erro ao gerar PDF: {e}")

    # 6. Atualiza controle
    doc_tomador = cliente.get("cnpj", cliente.get("cpf", ""))
    if atualizar_controle_nfs(n_nfse, data_emissao, doc_tomador, nome_tomador, cliente["valor"]):
        print(f"  Controle atualizado: NFS-e nº {n_nfse}")
    else:
        print(f"  AVISO: Controle de NFs não foi atualizado automaticamente.")

    return chave, n_nfse, xml_path, pdf_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Emissão automática de NFS-e — Portal Nacional (sefin.nfse.gov.br)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra o XML sem enviar")
    parser.add_argument("--cliente",
                        help="Nome parcial ou apelido do cliente")
    parser.add_argument("--emissor",
                        help="Nome do emissor no config (ex: samuel_mei)")
    parser.add_argument("--homologacao", action="store_true",
                        help="Força ambiente de homologação")
    parser.add_argument("--competencia",
                        help="Mês de competência YYYY-MM (padrão: mês atual)")
    args = parser.parse_args()

    config = carregar_config()
    emissor, nome_emissor = obter_emissor(config, args.emissor)
    clientes = emissor["clientes"]

    # Determina ambiente
    ambiente = "homologacao" if args.homologacao else config.get("ambiente", "homologacao")

    # Competência
    if args.competencia:
        competencia = args.competencia + "-01"
    else:
        competencia = datetime.now().strftime("%Y-%m-01")

    # Filtro de cliente
    if args.cliente:
        busca = args.cliente.lower()
        clientes = [c for c in clientes
                    if busca in c["nome"].lower() or busca in c.get("apelido", "").lower()]
        if not clientes:
            print(f"Nenhum cliente encontrado com '{args.cliente}'.")
            sys.exit(1)

    # Carrega certificado (se não for dry-run)
    cert_pem, key_pem = None, None
    if not args.dry_run:
        cert_pem, key_pem = carregar_certificado(emissor)
        if not cert_pem:
            print(f"Certificado não encontrado: {emissor['certificado']['pfx']}")
            print("Para dry-run (sem certificado): --dry-run")
            sys.exit(1)

    # Header
    modo = "DRY-RUN" if args.dry_run else f"{'HOMOLOGAÇÃO' if ambiente == 'homologacao' else 'PRODUÇÃO'}"
    print(f"\nEmissão NFS-e Nacional — {datetime.now().strftime('%d/%m/%Y %H:%M')} — {modo}")
    print(f"Emissor: {nome_emissor} (CNPJ {emissor['cnpj']})")
    print(f"Competência: {competencia[:7]}")
    print("=" * 65)

    erros = 0
    resultados_emissao = []
    for cliente in clientes:
        apelido = cliente.get("apelido", cliente["nome"][:30])
        valor = cliente["valor"]
        print(f"\n> {apelido}")
        print(f"  Valor: R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

        ndps = proximo_ndps(config, emissor)
        print(f"  DPS nº {ndps} (série {config['controle_dps']['serie']})")

        # Monta XML
        dps = montar_dps_xml(cliente, emissor, config, ndps, ambiente, competencia)
        xml_bytes = xml_para_string(dps)

        if args.dry_run:
            print("  XML gerado:")
            print(xml_bytes.decode("utf-8"))
            continue

        # Assina
        print("  Assinando XML...")
        xml_assinado = assinar_xml(xml_bytes, cert_pem, key_pem)

        # Comprime e codifica
        xml_b64 = comprimir_e_codificar(xml_assinado)
        print(f"  Payload: {len(xml_b64)} bytes (GZip+Base64)")

        # Envia
        print("  Enviando para o Portal Nacional...")
        resposta = enviar_dps(xml_b64, cert_pem, key_pem, ambiente)

        ok, msg = interpretar_retorno(resposta)
        status = "OK" if ok else "ERRO"
        print(f"  [{status}] {msg}")
        if not ok:
            erros += 1
            continue

        # Pós-emissão: baixa XML, salva, atualiza controle
        resultado = processar_pos_emissao(
            resposta, cliente, emissor, config, competencia,
            cert_pem, key_pem, ambiente
        )
        if resultado:
            chave, n_nfse, xml_path, pdf_path = resultado
            resultados_emissao.append({
                "apelido": apelido,
                "nome": cliente["nome"],
                "valor": valor,
                "chave": chave,
                "n_nfse": n_nfse,
                "xml_path": str(xml_path),
                "pdf_path": str(pdf_path) if pdf_path else None,
            })

    # Salva config (atualiza nDPS) se não for dry-run
    if not args.dry_run:
        salvar_config(config)

    print("\n" + "=" * 65)
    if args.dry_run:
        print(f"Dry-run concluído — {len(clientes)} XML(s) gerado(s). Nenhuma NF enviada.")
        print("Numeração NÃO foi incrementada.")
    elif erros == 0:
        print(f"Concluído — {len(clientes)} NF(s) emitida(s) com sucesso.")
        if resultados_emissao:
            print("\nResumo:")
            for r in resultados_emissao:
                print(f"  NFS-e nº {r['n_nfse']} — {r['apelido']} — R$ {r['valor']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            # Salva resultados para integração WhatsApp
            resultado_path = Path(__file__).parent / "ultima_emissao.json"
            resultado_json = {
                "data": datetime.now(FUSO_BR).isoformat(),
                "competencia": competencia[:7],
                "emissor": nome_emissor,
                "resultados": resultados_emissao,
            }
            resultado_path.write_text(json.dumps(resultado_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"\nResultados salvos em: {resultado_path}")

            # Agenda envio via WhatsApp às 09:00
            agendar_script = Path(__file__).parent / "agendar_whatsapp_nfse.py"
            if agendar_script.exists():
                print("\nAgendando envio via WhatsApp...")
                import subprocess
                ret = subprocess.run(
                    [sys.executable, str(agendar_script)],
                    capture_output=True, text=True
                )
                print(ret.stdout)
                if ret.stderr:
                    print(f"  AVISO WhatsApp: {ret.stderr[:300]}")
    else:
        print(f"Concluído com {erros} erro(s). Verifique acima.")
        sys.exit(1)


if __name__ == "__main__":
    main()
