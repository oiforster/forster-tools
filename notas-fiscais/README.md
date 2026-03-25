# 🧾 Processador de Notas Fiscais

Automatiza a organização e o lançamento de NFS-e (Notas Fiscais de Serviço Eletrônicas) a partir dos XMLs baixados da prefeitura. Renomeia as pastas no padrão `YYYY-MM - Razão Social` e lança cada NF no arquivo de controle correto.

---

## O que faz

1. Lê os XMLs de NFS-e em `Notas_Fiscais/`
2. Renomeia cada pasta para o padrão `YYYY-MM - Razão Social`
3. Lança a NF no arquivo `.md` de controle correspondente ao CNPJ emitente
4. Calcula e atualiza o total por ano automaticamente
5. Detecta NFs já lançadas (sem duplicatas)

---

## Configuração

**1. Copie o arquivo de exemplo:**
```bash
cp config.exemplo.json config.json
```

**2. Preencha com seus CNPJs:**
```json
{
  "cnpj_titular_1": "00000000000000",
  "cnpj_titular_2": "00000000000000",
  "arquivo_controle_1": "Controle_NFS_Titular1.md",
  "arquivo_controle_2": "Controle_NFS_Titular2.md"
}
```

---

## Uso

```bash
# Processamento real
python3 processar_nfs.py

# Simulação — mostra o que faria sem alterar nada
python3 processar_nfs.py --dry-run
```

---

## Estrutura esperada

```
_Financeiro/
├── processar_nfs.py
├── config.json
├── Controle_NFS_Titular1.md
├── Controle_NFS_Titular2.md
└── Notas_Fiscais/
    └── 2026/
        └── 35.935.852-0001-55/
            └── NF-001/
                └── nota.xml
```

---

## Formatos de NFS-e suportados

- **NFS-e Nacional (ABRASF)** — padrão nacional, maioria das prefeituras
- **NFS-e Municipal legado** — prefeituras que ainda usam formato próprio (ex: Igrejinha/RS)

---

## Requisitos

- Python 3.9+
- Nenhuma biblioteca externa — usa apenas a biblioteca padrão do Python
