# Notas Fiscais — Forster Filmes

Duas ferramentas para automacao completa de NFS-e: processamento dos XMLs recebidos e emissao automatica de novas notas.

---

## 1. Processador de NFS-e (`processar_nfs.py`)

Organiza e lanca NFS-e a partir dos XMLs baixados da prefeitura.

**O que faz:**
1. Le os XMLs de NFS-e em `Notas_Fiscais/`
2. Renomeia cada pasta para o padrao `YYYY-MM - Razao Social`
3. Lanca a NF no arquivo `.md` de controle correspondente ao CNPJ emitente
4. Calcula e atualiza o total por ano automaticamente
5. Detecta NFs ja lancadas (sem duplicatas)

**Uso:**
```bash
python3 processar_nfs.py             # processamento real
python3 processar_nfs.py --dry-run   # simulacao
```

**Configuracao:** copie `config.exemplo.json` para `config.json` e preencha os CNPJs.

**Localizacao dos arquivos de controle:** `_Financeiro/` no Synology Drive.

---

## 2. Emissor de NFS-e (`emitir_nfs_nacional.py`)

Emite NFS-e automaticamente via API do Portal Nacional (sefin.nfse.gov.br).

### Como funciona

1. Le o emissor ativo do `config_emissao.json` (suporta multiplos emissores)
2. Monta DPS (Declaracao de Prestacao de Servico) em XML padrao nacional
3. Assina o XML com certificado digital A1 (ICP-Brasil)
4. Comprime (GZip) e codifica (Base64)
5. Envia via POST JSON com mTLS para o Portal Nacional
6. Retorna chave de acesso e numero da NFS-e gerada

### Uso

```bash
# Ver o XML sem enviar (funciona sem certificado)
python3 emitir_nfs_nacional.py --dry-run

# Ver XML de um cliente especifico
python3 emitir_nfs_nacional.py --dry-run --cliente "Vanessa"

# Emitir no ambiente de teste (homologacao)
python3 emitir_nfs_nacional.py --homologacao

# Emitir em producao (real)
python3 emitir_nfs_nacional.py

# Emitir so para um cliente
python3 emitir_nfs_nacional.py --cliente "Micheline"

# Usar outro emissor (ex: Silvana)
python3 emitir_nfs_nacional.py --emissor silvana_simples

# Definir mes de competencia
python3 emitir_nfs_nacional.py --competencia 2026-04
```

### Configuracao

**1. Instalar dependencias:**
```bash
pip3 install --break-system-packages lxml signxml cryptography
```

**2. Configurar emissores:**

Copie `config_emissao.exemplo.json` para `config_emissao.json` e preencha:
- Dados do emissor (CNPJ, Inscricao Municipal)
- Dados dos clientes (CNPJ/CPF, endereco, valor mensal)
- Senha do certificado digital

**3. Certificado digital:**

Salve o arquivo `.pfx` (e-CNPJ A1) em `certificados/`:
```
certificados/samuel_mei.pfx       # MEI Samuel
certificados/silvana_simples.pfx  # Simples Nacional Silvana (futuro)
```

Na primeira execucao, o script extrai automaticamente `.pem` e `.key` do `.pfx`.

### Estrutura do config

```json
{
  "emissor_ativo": "samuel_mei",
  "emissores": {
    "samuel_mei": {
      "cnpj": "35935852000155",
      "regime": "MEI",
      "im": "",
      "certificado": { "pfx": "certificados/samuel_mei.pfx", "senha": "..." },
      "clientes": [
        { "apelido": "Vanessa", "cnpj": "...", "valor": 2000.00, ... }
      ]
    },
    "silvana_simples": { ... }
  },
  "servico": {
    "cTribNac": "130301",
    "CNBS": "114081300",
    "xDescServ": "Prestacao de servicos de producao audiovisual..."
  },
  "ambiente": "homologacao",
  "controle_dps": { "serie": "FORST", "proximo_nDPS": 1 }
}
```

### Emissores configurados

| Emissor | CNPJ | Regime | Status |
|---|---|---|---|
| samuel_mei | 35.935.852/0001-55 | MEI | Ativo — aguardando certificado A1 |
| silvana_simples | 18.129.107/0001-08 | Simples Nacional | Preparado — sem clientes ainda |

### Clientes do Samuel MEI

| Apelido | Tipo | Valor mensal |
|---|---|---|
| Vanessa | PJ (CNPJ 09.522.569/0001-91) | R$ 2.000,00 |
| Colegio | PJ (CNPJ 87.370.540/0001-45) | R$ 2.696,00 |
| Micheline | PF (CPF 653.678.550-91) | R$ 2.000,00 |

### Ambientes

| Ambiente | Endpoint | Uso |
|---|---|---|
| Homologacao | `sefin.producaorestrita.nfse.gov.br` | Testes (nao gera NF real) |
| Producao | `sefin.nfse.gov.br` | Emissao real |

### Numeracao DPS

O campo `proximo_nDPS` no config controla a numeracao sequencial. Em modo `--dry-run` a numeracao **nao** e incrementada. Em emissao real, o config e salvo automaticamente com o proximo numero.

---

## Estrutura de arquivos

```
notas-fiscais/
├── processar_nfs.py              # processador de XMLs recebidos
├── config.json                   # config do processador (gitignored)
├── config.exemplo.json           # template do processador
├── emitir_nfs_nacional.py        # emissor via Portal Nacional
├── config_emissao.json           # config do emissor (gitignored)
├── config_emissao.exemplo.json   # template do emissor
├── requirements.txt              # dependencias Python do emissor
├── certificados/                 # certificados digitais .pfx (gitignored)
│   ├── samuel_mei.pfx
│   └── silvana_simples.pfx
├── emitir_nfs_ipm_legado.py      # script antigo (IPM Fiscal) — arquivado
└── README.md                     # este arquivo
```

---

## Requisitos

- Python 3.9+
- `lxml`, `signxml`, `cryptography` (apenas para o emissor)
- Certificado digital e-CNPJ A1 ICP-Brasil (apenas para emissao real)
- macOS (testado em Apple Silicon)

---

## Documentacao de referencia

- Status completo do projeto: `Agencia/_Interno/Processos/Automacao_NFSe_IPM — Status e Retomada.md`
- Manual tecnico: Nota Control v1.01 (NFS-e Padrao Nacional, 25/11/2025)
- Portal Nacional: https://www.nfse.gov.br/EmissorNacional
- Documentacao API: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
