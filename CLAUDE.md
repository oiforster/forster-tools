# forster-tools — Instruções para Claude

Ferramentas de automação internas da Forster Boutique de Conteúdo.
Leia este arquivo antes de qualquer tarefa neste repositório.

---

## Estrutura do repositório

```
forster-tools/
├── notas-fiscais/     ← módulo principal desta sessão
├── auphonic/          ← automação Auphonic (separado)
└── reel-cover-generator/
```

---

## Módulo: notas-fiscais

### Emissores configurados (`config_emissao.json`)

| Chave | CNPJ | Regime | Sistema de emissão |
|---|---|---|---|
| `samuel_mei` | 35.935.852/0001-55 | MEI | Portal Nacional NFS-e (`emitir_nfs_nacional.py`) |
| `silvana_ltda` | 65.979.751/0001-47 | Simples Nacional ME | IPM WebService — Prefeitura de Igrejinha/RS (`emitir_nfs_ipm.py`) |

> **Importante:** Igrejinha/RS **não está no Portal Nacional NFS-e** (sefin.nfse.gov.br).
> O município usa o sistema IPM (plataforma Atende.Net). Toda emissão da silvana_ltda
> passa obrigatoriamente pelo `emitir_nfs_ipm.py`.

---

### Scripts principais

#### `emitir_nfs_ipm.py` — emissão silvana_ltda
- Autenticação: HTTP Basic Auth com **CNPJ** como usuário (não IM)
- Credencial: `base64(cnpj:senha_ipm)` — campo `senha_ipm` no config
- XML: multipart/form-data, campo `"f1"`, encoding ISO-8859-1
- Código TOM de Igrejinha: `8703` (campo `cMunGer_tom` no config; diferente do IBGE 4310108)
- Retorno: XML lean — só número, data, status e código verificador
- Sidecar: gera `logs/ipm_YYYY-MM-DD_HHmmSS_slug_dados.json` com todos os dados (prestador, tomador, serviço, valor) — necessário para o PDF
- Logs salvos em `logs/ipm_*.xml` e `logs/ipm_*_dados.json`

#### `emitir_nfs_nacional.py` — emissão samuel_mei
- Portal Nacional NFS-e (sefin.nfse.gov.br)
- mTLS com certificado A1 (.pfx)
- Gera `ultima_emissao.json` após cada lote

#### `gerar_pdf_nfse_ipm.js` — PDF para emissões IPM
- Input: `*_dados.json` sidecar (não o XML de retorno)
- Output: PDF no mesmo diretório do input
- Layout Notei (Plus Jakarta Sans + Be Vietnam Pro)
- Campos legais obrigatórios (Simples Nacional):
  - Regime tributário (badge verde no card do prestador)
  - Situação tributária (ex: "Tributado Integralmente" — tag verde)
  - ISS retido/não retido na fonte
  - Valor do ISS
  - Endereço do prestador

#### `gerar_pdf_nfse.js` — PDF para emissões Portal Nacional
- Input: XML da NFS-e retornado pelo portal
- Extrai regime (`opSimpNac`), situação (`tpTrib`), ISS retido (`tpRetISSQN !== '1'`)
- Mesmo layout visual do IPM

#### `agendar_whatsapp_nfse.py` — agendamento WhatsApp
- Lê `ultima_emissao.json` e insere em `~/Documents/forster-lembretes/agendados.json`
- Saudação automática por horário de Brasília (UTC-3):
  - 06:00–11:59 → "Bom dia"
  - 12:00–17:59 → "Boa tarde"
  - 18:00–05:59 → "Boa noite"
- `media` sempre como lista com **PDF + XML juntos**
- `xml_path` = XML de **retorno** da emissão (não o DPS enviado)
- Avisa explicitamente se PDF ou XML estiver ausente

#### `processar_nfs.py` (em `_Financeiro/`)
- Lê XMLs das pastas `Notas_Fiscais/AAAA/[Emissor]/[NF]/`
- Parsers: nacional ABRASF → municipal legado → sidecar `_dados.json` (fallback IPM)
- `parse_ipm_sidecar()`: acionado quando XML não contém tomador/valor (retorno IPM lean)
- Mapeamento de CNPJ → arquivo de controle:
  - `35935852000155` → `Controle_NFS_Samuel.md`
  - `18129107000108` → `Controle_NFS_Silvana.md`
  - `65979751000147` → `Controle_NFS_Forster_LTDA.md`

---

### Arquivos de controle (`_Financeiro/`)

| Arquivo | Cobre |
|---|---|
| `Controle_NFS_Samuel.md` | Samuel Rossano Forster — MEI 35.935.852/0001-55 |
| `Controle_NFS_Silvana.md` | Silvana Sparrenberger Forster — MEI 18.129.107/0001-08 — **até março/2026** |
| `Controle_NFS_Forster_LTDA.md` | Forster Boutique de Conteudo Ltda — 65.979.751/0001-47 — **a partir de abril/2026** |

---

### Estrutura de pastas NAS

```
_Financeiro/Notas_Fiscais/AAAA/
├── Samuel Rossano Forster - CNPJ 35935852000155/
│   └── YYYY-MM - Nome Tomador/
│       ├── *.xml   (retorno Portal Nacional)
│       └── *.pdf
├── Silvana Sparrenberger Forster - CNPJ 18129107000108/
│   └── YYYY-MM - Nome Tomador/  (até 03/2026)
└── Forster Boutique de Conteudo Ltda - CNPJ 65979751000147/
    └── YYYY-MM - Nome Tomador/  (a partir de 04/2026)
        ├── ipm_*.xml             (retorno IPM)
        ├── ipm_*_dados.json      (sidecar com todos os dados)
        └── ipm_*.pdf
```

---

### Bugs conhecidos / decisões técnicas

- **Auth IPM:** usuário = CNPJ (não IM). O campo `im` não deve entrar na cadeia de fallback.
- **`&` em razões sociais:** escapar com `html.escape()` antes de montar o XML.
- **`tpRetISSQN`:** no Portal Nacional, valor `1` = **não** retido (lógica inversa do esperado).
- **PDF path:** `gerar_pdf_nfse_ipm.js` usa `path.join(path.dirname(dadosPath), ...)` para garantir que o PDF fique no mesmo diretório do input.

---

### Pendências conhecidas (07/04/2026)

- [ ] Endereço completo do prestador (logradouro, número, bairro) no `config_emissao.json` para silvana_ltda — atualmente CEP only
- [ ] Testar emissão recorrente dos clientes fixos da silvana_ltda (Óticas, Catarata, Fyber, etc.)
- [ ] Avaliar automação mensal tipo `emitir_nfs_nacional.py` para o IPM
