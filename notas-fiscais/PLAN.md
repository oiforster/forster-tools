# Plano — Emissão NFS-e via Portal Nacional

## Contexto

A API do IPM Fiscal (Igrejinha) só funciona para Simples Nacional.
MEI precisa emitir pelo Portal Nacional NFS-e (sefin.nfse.gov.br).
O script `emitir_nfs.py` atual será reescrito para a nova API.

## Arquitetura

### Estrutura multi-emissor

O config suporta múltiplos emissores (Samuel MEI agora, Silvana Simples Nacional depois):

```
config_emissao.json
├── emissores
│   ├── samuel_mei        → CNPJ, regime, caminho do certificado, clientes
│   └── silvana_simples   → (futuro) idem
└── servico_padrao        → NBS, código, descrição
```

### Novo fluxo de emissão

```
1. Lê config → seleciona emissor
2. Para cada cliente:
   a. Monta DPS (XML no padrão nacional)
   b. Assina o XML com certificado A1
   c. Compacta (GZip) e codifica (Base64)
   d. Envia POST JSON para sefin.nfse.gov.br com mTLS
   e. Recebe NFS-e (chave de acesso, número, PDF)
3. Relatório final com status de cada emissão
```

### Autenticação

- **mTLS**: certificado A1 (.pfx → extraído para .pem + .key)
- **Assinatura XML**: xmlsec1 ou signxml (Python)
- Sem senha de portal — tudo via certificado

## Arquivos a criar/modificar

| Arquivo | Ação | Descrição |
|---|---|---|
| `emitir_nfs.py` | **reescrever** | Novo script para API Nacional |
| `config_emissao.exemplo.json` | **reescrever** | Novo formato multi-emissor |
| `config_emissao.json` | **reescrever** | Config real (gitignored) |
| `requirements.txt` | **criar** | Dependências: `signxml`, `lxml`, `cryptography` |
| `setup_certificado.py` | **criar** | Helper para extrair .pem/.key do .pfx |
| `README.md` | **atualizar** | Documentação do novo fluxo |

O script antigo do IPM será movido para `emitir_nfs_ipm_legado.py` (arquivamento).

## Dependências Python

```
lxml          → manipulação XML
signxml       → assinatura digital XML (envelope/enveloped)
cryptography  → leitura do certificado .pfx
requests      → HTTP com mTLS (mais ergonômico que urllib para certificados)
```

Instalação: `pip3 install lxml signxml cryptography requests`

## Etapas de implementação

### Fase 1 — Estrutura base (sem certificado, pode começar agora)
1. Reescrever `config_emissao.exemplo.json` no formato multi-emissor
2. Reescrever `emitir_nfs.py`:
   - Carregar config multi-emissor
   - Montar DPS XML no padrão nacional (campos do MEI)
   - `--dry-run` para ver o XML gerado
   - `--emissor` para selecionar qual emissor usar
   - `--cliente` para filtrar por nome
3. Criar `requirements.txt`
4. Modo `--dry-run` funciona sem certificado → podemos validar o XML

### Fase 2 — Assinatura e envio (quando tiver o certificado A1)
5. Criar `setup_certificado.py` (extrai .pem e .key do .pfx)
6. Implementar assinatura do XML com signxml
7. Implementar GZip + Base64 do XML assinado
8. Implementar envio via POST com mTLS
9. Implementar parsing da resposta (chave de acesso, número NF)
10. Testar no ambiente de Produção Restrita

### Fase 3 — Produção e agendamento
11. Trocar endpoint para produção
12. Emitir uma NF real de teste
13. Configurar launchd para dia 5 de cada mês

## Formato do XML DPS (padrão nacional MEI)

Baseado na documentação oficial e XSD v1.01:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<DPS xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.00">
  <infDPS Id="DPS_XXXXXXXX" versao="1.00">
    <tpAmb>2</tpAmb>                    <!-- 1=Prod, 2=Homolog -->
    <dhEmi>2026-03-28T10:00:00-03:00</dhEmi>
    <verAplic>ForsterTools1.0</verAplic>
    <serie>FORST</serie>
    <nDPS>1</nDPS>
    <dCompet>2026-03-01</dCompet>
    <prest>
      <CNPJ>35935852000155</CNPJ>
      <IM>XXXXX</IM>                    <!-- Inscrição Municipal -->
    </prest>
    <toma>
      <CNPJ>09522569000191</CNPJ>       <!-- ou CPF -->
      <xNome>VANESSA MAINARDI...</xNome>
      <end>
        <xLgr>Rua Joaquim Nabuco</xLgr>
        <nro>1685</nro>
        <xCpl>Sala 21</xCpl>
        <xBairro>Centro</xBairro>
        <cMun>4315004</cMun>            <!-- IBGE -->
        <UF>RS</UF>
        <CEP>93310002</CEP>
      </end>
    </toma>
    <serv>
      <cServ>1.03.01</cServ>            <!-- Subitem LC 116 -->
      <xDescServ>Produção audiovisual...</xDescServ>
      <CNBS>114081300</CNBS>
      <cTribNac>XXXXX</cTribNac>        <!-- código tributação nacional -->
    </serv>
    <valores>
      <vServPrest>
        <vServ>2000.00</vServ>
      </vServPrest>
    </valores>
  </infDPS>
</DPS>
```

## Campos que precisamos levantar

- [ ] **Inscrição Municipal** do Samuel em Igrejinha
- [ ] **Código de tributação nacional** (cTribNac) para produção audiovisual
- [ ] **Código IBGE** de cada cidade dos tomadores (substituir cidade_tom do IPM)
- [ ] **Série da DPS** — pode ser livre (ex: "FORST")
- [ ] **Numeração sequencial** — controlar localmente qual foi a última DPS emitida

## Observações

- O certificado A1 custa ~R$150-200/ano (e-CNPJ MEI)
- Recomendação: comprar na Certisign, Serasa ou AC Soluti
- O .pfx vem protegido por senha — o helper extrai .pem + .key
- Nunca commitar o certificado no Git
