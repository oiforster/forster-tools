#!/usr/bin/env python3
"""
processar_nfs.py — Forster Tools
==================================
Executa a partir de qualquer lugar. Busca automaticamente a pasta Notas_Fiscais
dentro do mesmo diretório onde este script está.

O que faz:
  1. Lê os XMLs de cada NF em Notas_Fiscais/
  2. Renomeia a pasta para o padrão  YYYY-MM - Razão Social
  3. Lança a NF no arquivo de controle correto com base no CNPJ emitente

Configuração:
  Copie config.exemplo.json → config.json e preencha com seus CNPJs.

Uso:
  python3 processar_nfs.py
  python3 processar_nfs.py --dry-run   (só mostra o que faria, sem alterar nada)
"""

import os, re, sys, json
from pathlib import Path
from datetime import datetime
from typing import Optional

# ─── Configuração ────────────────────────────────────────────────────────────

_config_path = Path(__file__).parent / 'config.json'
if not _config_path.exists():
    print("❌ config.json não encontrado.")
    print("   Copie config.exemplo.json → config.json e preencha com seus CNPJs.")
    sys.exit(1)

_cfg = json.loads(_config_path.read_text())

CNPJ_TITULAR_1 = re.sub(r'\D', '', _cfg.get('cnpj_titular_1', ''))
CNPJ_TITULAR_2 = re.sub(r'\D', '', _cfg.get('cnpj_titular_2', ''))

CONTROL_FILES = {
    CNPJ_TITULAR_1: _cfg.get('arquivo_controle_1', 'Controle_NFS_Titular1.md'),
    CNPJ_TITULAR_2: _cfg.get('arquivo_controle_2', 'Controle_NFS_Titular2.md'),
}

# Caracteres proibidos no Synology Cloud Sync
FORBIDDEN_CHARS = r'?:*"<>|\\#%{}$!+`'

# ─── Helpers ─────────────────────────────────────────────────────────────────

def fmt_cnpj(s: str) -> str:
    s = re.sub(r'\D', '', s)
    if len(s) == 14:
        return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"
    if len(s) == 11:
        return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"
    return s

def fmt_valor(s: str) -> str:
    try:
        v = float(s)
        return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return f"R$ {s}"

def parse_valor(s: str) -> float:
    """Converte 'R$ 1.234,56' → 1234.56"""
    s = re.sub(r'R\$\s*', '', s).strip()
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except Exception:
        return 0.0

def sanitize_name(name: str) -> str:
    """Remove/substitui caracteres proibidos no Synology."""
    for c in FORBIDDEN_CHARS:
        name = name.replace(c, '')
    return name.strip()

def title_case_razao(nome: str) -> str:
    """
    Converte 'INDUSTRIA DE COSMETICOS EFFE'S LTDA' para
    'Indústria de Cosméticos Effe's Ltda' — mantém artigos em minúsculo.
    """
    lower_words = {'de', 'da', 'do', 'das', 'dos', 'e', 'a', 'o', 'em', 'por', 'para', 'com', 'ao', 'à'}
    words = nome.strip().split()
    result = []
    for i, w in enumerate(words):
        if i == 0 or w.lower() not in lower_words:
            result.append(w.capitalize())
        else:
            result.append(w.lower())
    return ' '.join(result)

# ─── Leitura do XML ──────────────────────────────────────────────────────────

def parse_nfse_xml(xml_path: str) -> dict:
    """
    Extrai os campos relevantes de um XML de NFS-e nacional (ABRASF).
    Retorna dict com: nf, date, emitter_cnpj, toma_cnpj, toma_nome, valor, cancelada
    """
    try:
        with open(xml_path, 'r', encoding='utf-8', errors='replace') as f:
            raw = f.read()
    except Exception as e:
        return {'error': str(e)}

    def first(pattern, text=raw):
        m = re.search(pattern, text)
        return m.group(1) if m else None

    # Número da NF
    nf = first(r'<nNFSe>(\d+)</nNFSe>')

    # Data de emissão (prefere dhEmi, fallback dCompet)
    dh_emi   = first(r'<dhEmi>(\d{4}-\d{2}-\d{2})')
    d_compet = first(r'<dCompet>(\d{4}-\d{2}-\d{2})')

    # Se dCompet for muito anterior ao dhEmi (>6 meses), provavelmente erro — usa dhEmi
    date = dh_emi or d_compet
    if dh_emi and d_compet:
        try:
            diff = abs((datetime.fromisoformat(dh_emi) - datetime.fromisoformat(d_compet)).days)
            date = dh_emi if diff > 180 else d_compet
        except Exception:
            date = dh_emi

    # CNPJ emitente (para saber se é Samuel ou Silvana)
    emit_cnpj = first(r'<emit>.*?<CNPJ>(\d+)</CNPJ>', raw) or \
                first(r'<prest>.*?<CNPJ>(\d+)</CNPJ>', raw)

    # Tomador — bloco <toma>...</toma>
    toma_block = re.search(r'<toma>(.*?)</toma>', raw, re.DOTALL)
    toma_cnpj = toma_nome = None
    if toma_block:
        tb = toma_block.group(1)
        toma_cnpj = first(r'<CNPJ>(\d+)</CNPJ>', tb) or first(r'<CPF>(\d+)</CPF>', tb)
        toma_nome = first(r'<xNome>(.*?)</xNome>', tb)

    # Valor líquido
    valor = first(r'<vLiq>([\d.]+)</vLiq>') or first(r'<vServ>([\d.]+)</vServ>')

    # Cancelada? (cStat 101 = cancelada no padrão ABRASF)
    cstat = first(r'<cStat>(\d+)</cStat>')
    cancelada = cstat in ('101', '102')

    return {
        'nf':           nf or '?',
        'date':         date or '?',
        'emit_cnpj':    emit_cnpj or '',
        'toma_cnpj':    toma_cnpj or '',
        'toma_nome':    toma_nome or '?',
        'valor':        valor or '?',
        'cancelada':    cancelada,
    }

def parse_nfse_municipal(xml_path: str) -> dict:
    """
    Parser secundário para NFS-e no formato municipal legado (tag <nfse>).
    Cobre padrões como o de Igrejinha/RS onde os campos são diferentes do ABRASF nacional.
    """
    try:
        # Tenta UTF-8 primeiro, fallback para latin-1 (ISO-8859-1)
        try:
            with open(xml_path, 'r', encoding='utf-8', errors='replace') as f:
                raw = f.read()
        except Exception:
            with open(xml_path, 'r', encoding='latin-1', errors='replace') as f:
                raw = f.read()
    except Exception as e:
        return {'error': str(e)}

    def first(pattern, text=raw):
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else None

    # Número da NF
    nf = first(r'<numero_nfse>(\d+)</numero_nfse>')

    # Data — prefere data_nfse, fallback data_fato_gerador (formato dd/mm/yyyy)
    raw_date = first(r'<data_nfse>(\d{2}/\d{2}/\d{4})</data_nfse>') or \
               first(r'<data_fato_gerador>(\d{2}/\d{2}/\d{4})</data_fato_gerador>')
    date = None
    if raw_date:
        try:
            date = datetime.strptime(raw_date, '%d/%m/%Y').strftime('%Y-%m-%d')
        except Exception:
            pass

    # CNPJ emitente (prestador)
    emit_cnpj = first(r'<prestador>.*?<cpfcnpj>(\d+)</cpfcnpj>', raw)

    # Tomador
    toma_block = re.search(r'<tomador>(.*?)</tomador>', raw, re.DOTALL | re.IGNORECASE)
    toma_cnpj = toma_nome = None
    if toma_block:
        tb = toma_block.group(1)
        toma_cnpj = first(r'<cpfcnpj>(\d+)</cpfcnpj>', tb)
        toma_nome = first(r'<nome_razao_social>(.*?)</nome_razao_social>', tb)

    # Valor — formato brasileiro "2000,00" → converte para ponto
    valor_raw = first(r'<valor_total>([\d.,]+)</valor_total>')
    valor = None
    if valor_raw:
        valor = valor_raw.replace('.', '').replace(',', '.')

    # Cancelada — formato municipal geralmente não tem cStat; assume não cancelada
    cancelada = False

    return {
        'nf':        nf or '?',
        'date':      date or '?',
        'emit_cnpj': emit_cnpj or '',
        'toma_cnpj': toma_cnpj or '',
        'toma_nome': toma_nome or '?',
        'valor':     valor or '?',
        'cancelada': cancelada,
    }


def parse_xml(xml_path: str) -> dict:
    """
    Tenta o parser NFS-e nacional (ABRASF). Se não conseguir extrair número,
    tenta o parser municipal legado.
    """
    dados = parse_nfse_xml(xml_path)
    if 'error' in dados:
        return dados
    # Se não extraiu número, tenta o formato municipal
    if dados.get('nf') == '?':
        dados_mun = parse_nfse_municipal(xml_path)
        if 'error' not in dados_mun and dados_mun.get('nf') != '?':
            return dados_mun
    return dados


# ─── Renomeação de pastas ────────────────────────────────────────────────────

def nova_pasta(data: dict) -> Optional[str]:
    """
    Gera o novo nome para a pasta no padrão YYYY-MM - Razão Social.
    Retorna None se não houver dados suficientes.
    """
    date = data.get('date', '')
    nome = data.get('toma_nome', '')
    cancelada = data.get('cancelada', False)

    if not date or date == '?' or not nome or nome == '?':
        return None

    try:
        dt = datetime.fromisoformat(date[:10])
        prefixo = dt.strftime('%Y-%m')
    except Exception:
        return None

    razao = title_case_razao(nome)
    razao = sanitize_name(razao)

    nome_pasta = f"{prefixo} - {razao}"
    if cancelada:
        nome_pasta += ' (cancelada)'
    return nome_pasta

def renomear_pasta(pasta_path: str, novo_nome: str, dry_run: bool) -> str:
    """
    Renomeia a pasta. Se o novo nome já existe, adiciona sufixo numérico.
    Retorna o caminho final.
    """
    parent = os.path.dirname(pasta_path)
    destino = os.path.join(parent, novo_nome)

    if os.path.abspath(pasta_path) == os.path.abspath(destino):
        return pasta_path  # já tem o nome certo

    # Conflito de nome?
    if os.path.exists(destino):
        i = 2
        while True:
            tentativa = os.path.join(parent, f"{novo_nome} ({i})")
            if not os.path.exists(tentativa):
                destino = tentativa
                break
            i += 1

    if not dry_run:
        os.rename(pasta_path, destino)
    return destino

# ─── Atualização do arquivo de controle ──────────────────────────────────────

def nf_ja_existe(conteudo: str, nf_num: str, ano: str) -> bool:
    """Verifica se a NF já está registrada no ano correto."""
    if ano == '????':
        return False
    # Encontra a seção do ano (escapa ano para evitar problemas no regex)
    secao = re.search(rf'## {re.escape(ano)}(.*?)(?=\n## |\Z)', conteudo, re.DOTALL)
    if not secao:
        return False
    # Procura pelo número na tabela (coluna 1) — aceita sufixos como * ou (n)
    pattern = rf'^\|\s*{re.escape(nf_num)}[\s*]*\|'
    return bool(re.search(pattern, secao.group(1), re.MULTILINE))

def calcular_total(tabela: str) -> float:
    """Soma os valores das linhas que não estão marcadas como Cancelada."""
    total = 0.0
    for linha in tabela.splitlines():
        if not linha.startswith('|') or linha.startswith('|--') or linha.startswith('| Nº'):
            continue
        colunas = [c.strip() for c in linha.split('|')]
        if len(colunas) < 7:
            continue
        obs = colunas[6].lower() if len(colunas) > 6 else ''
        if 'cancelada' in obs:
            continue
        valor_str = colunas[5] if len(colunas) > 5 else ''
        total += parse_valor(valor_str)
    return total

def inserir_linha_controle(conteudo: str, ano: str, nova_linha: str, data_nf: str) -> str:
    """
    Insere a nova linha na tabela do ano correspondente, em ordem cronológica.
    Se a seção do ano não existir, cria antes da seção anterior mais recente.
    """
    ano_esc = re.escape(ano)
    secao_pat = re.compile(rf'(## {ano_esc}\n)(.*?)(\*\*Total {ano_esc}:.*?\n)', re.DOTALL)
    match = secao_pat.search(conteudo)

    if not match:
        # Seção não existe — cria entre o header e a próxima seção mais antiga
        cabecalho = (
            f"\n## {ano}\n\n"
            f"| Nº NFS-e | Data Emissão | CPF/CNPJ Tomador | Nome Tomador | Valor | Obs |\n"
            f"|----------|-------------|-----------------|-------------|-------|-----|\n"
            f"{nova_linha}\n\n"
            f"**Total {ano}:** R$ 0,00\n"
        )
        # Insere depois do bloco de notas no topo (antes do primeiro ##)
        primeiro_secao = re.search(r'\n## \d{4}', conteudo)
        if primeiro_secao:
            pos = primeiro_secao.start()
            conteudo = conteudo[:pos] + cabecalho + conteudo[pos:]
        else:
            conteudo += cabecalho
        # Recalcula com a linha recém-adicionada
        return recalcular_total(conteudo, ano)

    tabela_atual = match.group(2)

    # Insere a linha na posição correta (ordem cronológica por data)
    linhas = tabela_atual.splitlines(keepends=True)
    inserido = False
    nova_linhas = []
    for linha in linhas:
        if not inserido and linha.startswith('|') and not linha.startswith('|--') and not linha.startswith('| Nº'):
            # Extrai a data desta linha para comparar
            cols = [c.strip() for c in linha.split('|')]
            data_linha = cols[2] if len(cols) > 2 else ''
            try:
                dt_linha  = datetime.strptime(data_linha, '%d/%m/%Y')
                dt_nova   = datetime.strptime(data_nf,    '%d/%m/%Y')
                if dt_nova < dt_linha:
                    nova_linhas.append(nova_linha + '\n')
                    inserido = True
            except Exception:
                pass
        nova_linhas.append(linha)
    if not inserido:
        # Insere antes da linha de total
        nova_linhas.append(nova_linha + '\n')

    nova_tabela = ''.join(nova_linhas)
    conteudo = conteudo[:match.start(2)] + nova_tabela + conteudo[match.start(3):]
    return recalcular_total(conteudo, ano)

def recalcular_total(conteudo: str, ano: str) -> str:
    """Recalcula e atualiza a linha de total de um ano."""
    ano_esc = re.escape(ano)
    secao_pat = re.compile(rf'(## {ano_esc}\n)(.*?)(\*\*Total {ano_esc}:.*?\n)', re.DOTALL)
    match = secao_pat.search(conteudo)
    if not match:
        return conteudo
    total = calcular_total(match.group(2))
    total_fmt = fmt_valor(str(total))
    # Mantém nota sobre canceladas se existir
    linha_total_atual = match.group(3)
    nota = ''
    m_nota = re.search(r'\*(NF.*?)\*', linha_total_atual)
    if m_nota:
        nota = f' *({m_nota.group(1)})*'
    nova_total = f"**Total {ano}:** {total_fmt}{nota}\n"
    return conteudo[:match.start(3)] + nova_total + conteudo[match.end(3):]

def atualizar_controle(controle_path: str, nf_data: dict, dry_run: bool) -> bool:
    """
    Adiciona a NF ao arquivo de controle se ainda não estiver presente.
    Retorna True se houve alteração.
    """
    if not os.path.exists(controle_path):
        print(f"  ⚠ Arquivo de controle não encontrado: {controle_path}")
        return False

    with open(controle_path, 'r', encoding='utf-8') as f:
        conteudo = f.read()

    nf_num = nf_data['nf']
    date   = nf_data['date']
    ano    = date[:4] if date != '?' else '????'

    if nf_ja_existe(conteudo, nf_num, ano):
        return False  # já registrada

    # Formata a linha da tabela
    cnpj_fmt  = fmt_cnpj(nf_data['toma_cnpj']) if nf_data['toma_cnpj'] else '—'
    nome      = title_case_razao(nf_data['toma_nome'])
    valor_fmt = fmt_valor(nf_data['valor'])
    obs       = 'Cancelada' if nf_data['cancelada'] else ''
    try:
        dt    = datetime.fromisoformat(date[:10])
        data_fmt = dt.strftime('%d/%m/%Y')
    except Exception:
        data_fmt = date

    nova_linha = f"| {nf_num} | {data_fmt} | {cnpj_fmt} | {nome} | {valor_fmt} | {obs} |"

    novo_conteudo = inserir_linha_controle(conteudo, ano, nova_linha, data_fmt)

    if not dry_run:
        with open(controle_path, 'w', encoding='utf-8') as f:
            f.write(novo_conteudo)

    return True

# ─── Main ────────────────────────────────────────────────────────────────────

def find_script_dir_real() -> str:
    """
    Retorna o caminho real (com encoding NFD do macOS) do diretório onde o
    script está. Necessário porque Path(__file__).resolve() retorna NFC,
    mas o Google Drive sincroniza pastas com encoding NFD no Linux.
    Estratégia: percorre o path de cima para baixo usando os.listdir().
    """
    import unicodedata

    # Path resolvido pelo Python (pode ser NFC)
    nfc_path = str(Path(__file__).resolve().parent)
    segments = nfc_path.split('/')  # ex: ['', 'sessions', ..., 'Agência', '_Financeiro']

    real = ''
    for seg in segments:
        if seg == '':
            real = '/'
            continue
        try:
            entries = os.listdir(real if real != '/' else '/')
        except Exception:
            real = os.path.join(real, seg)
            continue

        matched = None
        seg_nfc = unicodedata.normalize('NFC', seg)
        for entry in entries:
            entry_nfc = unicodedata.normalize('NFC', entry)
            if entry_nfc == seg_nfc:
                matched = entry
                break
        real = os.path.join(real, matched if matched else seg)

    return real


def main():
    dry_run = '--dry-run' in sys.argv

    if dry_run:
        print("🔍 MODO DRY-RUN — nenhuma alteração será feita\n")

    # Encontra o diretório base com o encoding real do sistema de arquivos
    script_dir = find_script_dir_real()
    nf_base    = os.path.join(script_dir, 'Notas_Fiscais')

    if not os.path.exists(nf_base):
        print(f"❌ Pasta 'Notas_Fiscais' não encontrada em {script_dir}")
        sys.exit(1)

    renomeadas = 0
    lancadas   = 0
    erros      = []

    print(f"📂 Processando: {nf_base}\n")

    for year_dir in sorted(Path(nf_base).iterdir()):
        if not year_dir.is_dir(): continue

        for person_dir in sorted(year_dir.iterdir()):
            if not person_dir.is_dir() or person_dir.name == '.DS_Store': continue

            # Identifica CNPJ da pessoa por nome da pasta
            emit_cnpj = None
            if CNPJ_SAMUEL in person_dir.name.replace('.','').replace('/','').replace('-',''):
                emit_cnpj = CNPJ_SAMUEL
            elif CNPJ_SILVANA in person_dir.name.replace('.','').replace('/','').replace('-',''):
                emit_cnpj = CNPJ_SILVANA

            for nf_dir in sorted(person_dir.iterdir()):
                if not nf_dir.is_dir() or nf_dir.name == '.DS_Store': continue

                # Busca XML
                xmls = [f for f in nf_dir.iterdir() if f.suffix.lower() == '.xml' and not f.name.startswith('.')]
                if not xmls:
                    continue

                xml_path = xmls[0]
                dados = parse_xml(str(xml_path))

                if 'error' in dados:
                    erros.append(f"{nf_dir} → {dados['error']}")
                    continue

                # Prioridade: nome da pasta (mais confiável) > CNPJ do XML
                cnpj_emit = emit_cnpj or dados.get('emit_cnpj', '') or ''

                # ── 1. Renomear pasta ──────────────────────────────────────
                novo_nome = nova_pasta(dados)
                pasta_atual = str(nf_dir)

                # Só renomeia se NÃO estiver ainda no padrão YYYY-MM
                ja_no_padrao = bool(re.match(r'^\d{4}-\d{2} - .+', nf_dir.name))

                if not ja_no_padrao:
                    if novo_nome:
                        print(f"  📁 {year_dir.name}/{person_dir.name}/")
                        print(f"     {nf_dir.name}")
                        print(f"  → {novo_nome}")
                        novo_caminho = renomear_pasta(pasta_atual, novo_nome, dry_run)
                        pasta_atual = novo_caminho
                        renomeadas += 1
                    else:
                        erros.append(f"Sem dados suficientes para renomear: {nf_dir.name}")

                # ── 2. Lançar no controle ──────────────────────────────────
                            # Pula NFs sem número (não dá pra verificar duplicata)
                if dados['nf'] == '?':
                    erros.append(f"NF sem número detectado (XML fora do padrão NFS-e nacional?): {nf_dir.name}")
                elif cnpj_emit in CONTROL_FILES:
                    controle_nome = CONTROL_FILES[cnpj_emit]
                    controle_path = os.path.join(script_dir, controle_nome)
                    alterado = atualizar_controle(controle_path, dados, dry_run)
                    if alterado:
                        acao = "(simulado)" if dry_run else "✓"
                        print(f"  📝 {acao} NF#{dados['nf']} → {controle_nome}")
                        lancadas += 1
                else:
                    erros.append(f"CNPJ emitente desconhecido ({cnpj_emit}) em: {nf_dir.name}")

    # ── Resumo ────────────────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"✅ Pastas renomeadas:  {renomeadas}")
    print(f"✅ NFs lançadas:       {lancadas}")
    if erros:
        print(f"\n⚠  Atenção ({len(erros)} itens):")
        for e in erros:
            print(f"   • {e}")

if __name__ == '__main__':
    main()
